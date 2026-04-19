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
  String _status = 'Initializing...';
  String _lastDetection = '';

  // ── mic state ─────────────────────────────────────────────
  bool _micActive = false;
  bool _isListening = false;

  // ── queue ─────────────────────────────────────────────────
  final List<Map<String, dynamic>> _queue = [];
  bool _queueRunning = false;
  bool _isSpeaking = false;

  // ── warning dedup ─────────────────────────────────────────
  String _lastQueuedPhrase = '';
  int _lastQueuedMs = 0;

  static String get _wsUrl => AppConfig.websocketUrl;

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
      if (mounted) setState(() => _status = 'Hold to search');
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

    if (_micActive) return;

    final phrase = _buildWarningPhrase(data);
    final urgency = data['urgency'] as String;
    final now = DateTime.now().millisecondsSinceEpoch;

    final cooldown = urgency == 'high' ? 800 : 3000;
    final isDuplicate =
        phrase == _lastQueuedPhrase && (now - _lastQueuedMs) < cooldown;

    if (isDuplicate) return;

    _lastQueuedPhrase = phrase;
    _lastQueuedMs = now;

    if (urgency == 'high') {
      _queue.clear();
      _tts.stop();
      _queue.insert(0, {'phrase': phrase, 'priority': true});
    } else {
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

    _queue.clear();
    _tts.stop();
    _lastQueuedPhrase = '';
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
        if (_micActive) {
          await Future.delayed(const Duration(milliseconds: 50));
          continue;
        }

        if (_queue.isEmpty) {
          await Future.delayed(const Duration(milliseconds: 50));
          continue;
        }

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

    _tts.stop();
    _queue.clear();

    await _stt.startListening();
    if (mounted) setState(() => _isListening = true);
  }

  Future<void> _onMicRelease() async {
    if (!_micActive) return;

    if (mounted) setState(() => _isListening = true);

    final object = await _stt.stopAndTranscribe();
    print('[STT] Got: $object');

    _micActive = false;
    _lastQueuedPhrase = '';
    _lastQueuedMs = 0;

    if (mounted) setState(() => _isListening = false);

    if (object != null && object.trim().isNotEmpty) {
      final q = object.trim();
      _channel.sink.add(jsonEncode({'type': 'search', 'query': q}));
      if (mounted) setState(() => _lastDetection = 'Searching for $q...');
    }
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
    if (phrase.contains('Searching')) return Colors.blue.shade300;
    return Colors.green.shade400;
  }

  // ── ui ────────────────────────────────────────────────────

  @override
  Widget build(BuildContext context) {
    final color =
        _lastDetection.isEmpty ? Colors.white24 : _phraseColor(_lastDetection);

    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: Center(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 40),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                // Title
                const Icon(Icons.hearing, color: Colors.white24, size: 36),
                const SizedBox(height: 12),
                const Text(
                  'Vision Assistant',
                  style: TextStyle(
                    color: Colors.white38,
                    fontSize: 18,
                    fontWeight: FontWeight.w300,
                    letterSpacing: 3,
                  ),
                ),

                const SizedBox(height: 64),

                // Status dot
                AnimatedContainer(
                  duration: const Duration(milliseconds: 300),
                  width: 8,
                  height: 8,
                  decoration: BoxDecoration(
                    color: color,
                    shape: BoxShape.circle,
                  ),
                ),
                const SizedBox(height: 20),

                // Detection text
                Text(
                  _lastDetection.isEmpty ? 'No detections yet' : _lastDetection,
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    color: _lastDetection.isEmpty ? Colors.white24 : color,
                    fontSize: 20,
                    fontWeight: FontWeight.w400,
                    height: 1.6,
                  ),
                ),

                const SizedBox(height: 72),

                // Mic button
                GestureDetector(
                  onTapDown: (_) => _onMicHold(),
                  onTapUp: (_) => _onMicRelease(),
                  onTapCancel: () => _onMicRelease(),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 200),
                    width: 80,
                    height: 80,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: _isListening
                          ? Colors.red.shade900
                          : _micActive
                              ? Colors.blue.shade900
                              : Colors.white.withOpacity(0.07),
                      border: Border.all(
                        color: _isListening
                            ? Colors.red.shade400
                            : _micActive
                                ? Colors.blue.shade400
                                : Colors.white24,
                        width: 1.5,
                      ),
                    ),
                    child: Icon(
                      _isListening
                          ? Icons.mic
                          : _micActive
                              ? Icons.hourglass_top
                              : Icons.mic_none,
                      color: _isListening || _micActive
                          ? Colors.white
                          : Colors.white38,
                      size: 30,
                    ),
                  ),
                ),

                const SizedBox(height: 16),

                // Status label
                Text(
                  _isListening
                      ? 'Listening...'
                      : _micActive
                          ? 'Transcribing...'
                          : _status,
                  style: const TextStyle(
                    color: Colors.white24,
                    fontSize: 12,
                    letterSpacing: 1,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
