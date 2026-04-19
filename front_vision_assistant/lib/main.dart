import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'tts/tts_factory.dart';
import 'stt_service.dart';
import 'config.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const VisionAssistantApp());
}

class VisionAssistantApp extends StatelessWidget {
  const VisionAssistantApp({super.key});

  @override
  Widget build(BuildContext context) {
    return const MaterialApp(
      debugShowCheckedModeBanner: false,
      home: VisionScreen(),
    );
  }
}

class VisionScreen extends StatefulWidget {
  const VisionScreen({super.key});

  @override
  State<VisionScreen> createState() => _VisionScreenState();
}

class _VisionScreenState extends State<VisionScreen> {
  // ── services ──────────────────────────────────────────────
  late WebSocketChannel _channel;
  final TtsService _tts = TtsService();
  final SttService _stt = SttService();

  // ── app state ─────────────────────────────────────────────
  bool _ready = false;
  bool _started = false;
  String _status = 'Initializing...';
  String _lastDetection = '';

  // ── mic state (single flag) ────────────────────────────────
  bool _micActive = false;
  bool _isListening = false; // UI only

  // ── queue ─────────────────────────────────────────────────
  // Each item: { 'phrase': String, 'priority': bool }
  final List<Map<String, dynamic>> _queue = [];
  bool _queueRunning = false;
  bool _isSpeaking = false;

  // ── warning dedup ─────────────────────────────────────────
  // Only used in _onMessage to avoid flooding the queue
  String _lastQueuedPhrase = '';
  int _lastQueuedMs = 0;

  String get _wsUrl => AppConfig.websocketUrl;

  // ── lifecycle ─────────────────────────────────────────────

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _init());
  }

  Future<void> _init() async {
    try {
      await AppConfig.load();
      await _tts.init();
      await _stt.init();
      _connect();
      _startQueueLoop();
      if (mounted)
        setState(() {
          _status = 'Ready';
          _ready = true;
        });
    } catch (e) {
      if (mounted) setState(() => _status = 'Init error: $e');
    }
  }

  @override
  void dispose() {
    _channel.sink.close();
    _tts.stop();
    _stt.stop();
    super.dispose();
  }

  // ── websocket ─────────────────────────────────────────────

  void _connect() {
    try {
      _channel = WebSocketChannel.connect(Uri.parse(_wsUrl));
      _channel.stream.listen(
        _onMessage,
        onDone: () => Future.delayed(const Duration(seconds: 2), _connect),
        onError: (_) => Future.delayed(const Duration(seconds: 2), _connect),
      );
    } catch (_) {
      Future.delayed(const Duration(seconds: 2), _connect);
    }
  }

  void _onMessage(dynamic raw) {
    final data = jsonDecode(raw as String) as Map<String, dynamic>;
    final type = data['type'] as String? ?? 'obstacle';

    if (type == 'search_result') {
      _onSearchResult(data);
      return;
    }

    // Don't queue warnings before user starts or while mic is active
    if (!_started || _micActive) return;

    final phrase = _buildWarningPhrase(data);
    final urgency = data['urgency'] as String;
    final now = DateTime.now().millisecondsSinceEpoch;

    // Dedup: same phrase within cooldown window → skip
    // High urgency has shorter cooldown and always interrupts
    final cooldown = urgency == 'high' ? 800 : 3000;
    final isDuplicate =
        phrase == _lastQueuedPhrase && (now - _lastQueuedMs) < cooldown;

    if (isDuplicate) return;

    _lastQueuedPhrase = phrase;
    _lastQueuedMs = now;

    // High urgency: clear queue, stop current speech, jump to front
    if (urgency == 'high') {
      _queue.clear();
      _tts.stop();
      _queue.insert(0, {'phrase': phrase, 'priority': true});
    } else {
      // Only add if queue isn't already backed up
      if (_queue.length < 3) {
        _queue.add({'phrase': phrase, 'priority': false});
      }
    }

    if (mounted) setState(() => _lastDetection = phrase);
  }

  void _onSearchResult(Map<String, dynamic> data) {
    final found = data['found'] as bool;
    final query = data['query'] as String;

    final phrase = found
        ? '$query is ${(data['distance'] as num).toStringAsFixed(1)} meters, ${data['direction']}'
        : '$query not detected nearby';

    // Interrupt everything, speak result immediately
    _queue.clear();
    _tts.stop();
    _lastQueuedPhrase = ''; // reset so warnings resume after result
    _lastQueuedMs = 0;

    _queue.insert(0, {'phrase': phrase, 'priority': true});

    if (mounted) setState(() => _lastDetection = phrase);
  }

  // ── queue loop ────────────────────────────────────────────

  Future<void> _startQueueLoop() async {
    if (_queueRunning) return;
    _queueRunning = true;

    while (true) {
      try {
        // Pause while mic is recording or transcribing
        if (_micActive) {
          await Future.delayed(const Duration(milliseconds: 50));
          continue;
        }

        // Nothing to say
        if (_queue.isEmpty) {
          await Future.delayed(const Duration(milliseconds: 50));
          continue;
        }

        // Take next item — priority first
        final idx = _queue.indexWhere((d) => d['priority'] == true);
        final item = idx != -1 ? _queue.removeAt(idx) : _queue.removeAt(0);
        final phrase = item['phrase'] as String;

        _isSpeaking = true;
        if (mounted) setState(() {});

        try {
          await _tts.synthesizeAndPlay(phrase);
        } catch (e) {
          print('[QUEUE] Speak error: $e');
        }

        _isSpeaking = false;
        print('[QUEUE] Done. Remaining: ${_queue.length}');
        if (mounted) setState(() {});
      } catch (e) {
        print('[QUEUE] Loop error: $e');
        _isSpeaking = false;
        if (mounted) setState(() {});
        await Future.delayed(const Duration(milliseconds: 200));
      }
    }
  }

  // ── mic ───────────────────────────────────────────────────

  Future<void> _onMicHold() async {
    if (_micActive) return;
    _micActive = true;

    // Stop speech and clear pending warnings
    _tts.stop();
    _queue.clear();

    await _stt.startListening();
    if (mounted) setState(() => _isListening = true);
  }

  Future<void> _onMicRelease() async {
    if (!_micActive) return;

    // Keep button red while transcribing
    if (mounted) setState(() => _isListening = true);

    final object = await _stt.stopAndTranscribe();
    print('[STT] Got: $object');

    // Release mic — queue loop resumes automatically
    _micActive = false;
    // Reset dedup so first warning after mic release always plays
    _lastQueuedPhrase = '';
    _lastQueuedMs = 0;

    if (mounted) setState(() => _isListening = false);

    if (object != null && object.trim().isNotEmpty) {
      final q = object.trim();
      _channel.sink.add(jsonEncode({'type': 'search', 'query': q}));
      if (mounted) setState(() => _lastDetection = 'Searching for $q...');
    }
    // If null, mic just releases and warnings resume — nothing else needed
  }

  // ── helpers ───────────────────────────────────────────────

  String _buildWarningPhrase(Map<String, dynamic> d) {
    final label = d['label'] as String;
    final distance = (d['distance'] as num).toStringAsFixed(1);
    final direction = d['direction'] as String;
    final urgency = d['urgency'] as String;

    if (urgency == 'high') return 'Stop! $label very close, move $direction';
    if (urgency == 'medium')
      return '$label at $distance meters, move $direction';
    return '$label ahead, $distance meters';
  }

  Color _phraseColor(String phrase) {
    if (phrase.startsWith('Stop!')) return Colors.red.shade400;
    if (phrase.contains('meters, move')) return Colors.orange.shade400;
    return Colors.green.shade400;
  }

  // ── ui ────────────────────────────────────────────────────

  Future<void> _onStart() async {
    await _tts.unlock();
    setState(() {
      _started = true;
      _status = 'Listening...';
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: _started ? _buildMain() : _buildStart(),
      ),
    );
  }

  Widget _buildStart() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(Icons.hearing, color: Colors.white54, size: 64),
          const SizedBox(height: 24),
          const Text(
            'Vision Assistant',
            style: TextStyle(
              color: Colors.white,
              fontSize: 28,
              fontWeight: FontWeight.w300,
              letterSpacing: 2,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            _status,
            style: const TextStyle(color: Colors.white38, fontSize: 14),
          ),
          const SizedBox(height: 48),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
              padding: const EdgeInsets.symmetric(horizontal: 48, vertical: 20),
              backgroundColor: Colors.white,
              foregroundColor: Colors.black,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(12),
              ),
            ),
            onPressed: _ready ? _onStart : null,
            child: Text(
              _ready ? 'Start Listening' : 'Initializing...',
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w500),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildMain() {
    final color =
        _lastDetection.isEmpty ? Colors.white24 : _phraseColor(_lastDetection);

    return Padding(
      padding: const EdgeInsets.all(32),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          // Status dot
          AnimatedContainer(
            duration: const Duration(milliseconds: 300),
            width: 12,
            height: 12,
            decoration: BoxDecoration(
              color: color,
              shape: BoxShape.circle,
            ),
          ),
          const SizedBox(height: 32),

          // Detection text
          Text(
            _lastDetection.isEmpty ? 'No detections yet' : _lastDetection,
            textAlign: TextAlign.center,
            style: TextStyle(
              color: _lastDetection.isEmpty ? Colors.white24 : color,
              fontSize: 22,
              fontWeight: FontWeight.w400,
              height: 1.5,
            ),
          ),
          const SizedBox(height: 32),

          // Speaking indicator
          AnimatedOpacity(
            opacity: _isSpeaking ? 1.0 : 0.0,
            duration: const Duration(milliseconds: 200),
            child: const Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.volume_up, color: Colors.white38, size: 16),
                SizedBox(width: 6),
                Text('Speaking...',
                    style: TextStyle(color: Colors.white38, fontSize: 13)),
              ],
            ),
          ),

          const Spacer(),

          // Mic button
          GestureDetector(
            onTapDown: (_) => _onMicHold(),
            onTapUp: (_) => _onMicRelease(),
            onTapCancel: () => _onMicRelease(),
            child: AnimatedContainer(
              duration: const Duration(milliseconds: 200),
              width: 72,
              height: 72,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: _isListening ? Colors.red.shade800 : Colors.white12,
                border: Border.all(
                  color: _isListening ? Colors.red : Colors.white24,
                  width: 1.5,
                ),
              ),
              child: Icon(
                _isListening ? Icons.mic : Icons.mic_none,
                color: _isListening ? Colors.white : Colors.white54,
                size: 28,
              ),
            ),
          ),
          const SizedBox(height: 12),
          Text(
            _isListening
                ? 'Listening... say "where\'s [object]"'
                : 'Hold to ask',
            style: const TextStyle(color: Colors.white24, fontSize: 12),
          ),
          const SizedBox(height: 24),

          // Stop button
          TextButton(
            onPressed: () {
              _tts.stop();
              _queue.clear();
              _micActive = false;
              setState(() {
                _started = false;
                _isListening = false;
                _lastDetection = '';
                _lastQueuedPhrase = '';
                _lastQueuedMs = 0;
                _status = 'Ready';
              });
            },
            child: const Text(
              'Stop',
              style: TextStyle(color: Colors.white24, fontSize: 14),
            ),
          ),
        ],
      ),
    );
  }
}
