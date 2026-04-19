import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
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
  final SttService _stt = SttService();

  // ── app state ─────────────────────────────────────────────
  String _status = 'Initializing...';
  String _lastDetection = '';

  // ── mic state ─────────────────────────────────────────────
  bool _micActive = false;
  bool _isListening = false;

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
      await _stt.init();
      _connect();
      if (mounted) setState(() => _status = 'Hold to search');
    } catch (e) {
      if (mounted) setState(() => _status = 'Init error: $e');
    }
  }

  @override
  void dispose() {
    _channel.sink.close();
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
    if (mounted) setState(() => _lastDetection = phrase);
  }

  void _onSearchResult(Map<String, dynamic> data) {
    final found = data['found'] as bool;
    final query = data['query'] as String;

    final phrase = found
        ? '$query is ${(data['distance'] as num).toStringAsFixed(1)} meters, ${data['direction']}'
        : '$query not detected nearby';

    if (mounted) setState(() => _lastDetection = phrase);
  }

  // ── mic ───────────────────────────────────────────────────

  Future<void> _onMicHold() async {
    if (_micActive) return;
    _micActive = true;

    await _stt.startListening();
    if (mounted) setState(() => _isListening = true);
  }

  Future<void> _onMicRelease() async {
    if (!_micActive) return;

    if (mounted) setState(() => _isListening = true);

    final object = await _stt.stopAndTranscribe();
    print('[STT] Got: $object');

    _micActive = false;

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
                const Icon(Icons.hearing, color: Colors.white24, size: 130),
                const SizedBox(height: 60),
                const Text(
                  'Vision Assistant',
                  style: TextStyle(
                    color: Colors.white38,
                    fontSize: 40,
                    fontWeight: FontWeight.w300,
                    letterSpacing: 3,
                  ),
                ),
                const SizedBox(height: 200),
                GestureDetector(
                  onTapDown: (_) => _onMicHold(),
                  onTapUp: (_) => _onMicRelease(),
                  onTapCancel: () => _onMicRelease(),
                  child: AnimatedContainer(
                    duration: const Duration(milliseconds: 200),
                    width: 350,
                    height: 350,
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
                      size: 100,
                    ),
                  ),
                ),
                const SizedBox(height: 16),
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
