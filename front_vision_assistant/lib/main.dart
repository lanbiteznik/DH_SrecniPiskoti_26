import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'tts/tts_factory.dart';
import 'config.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // Load environment variables from .env file
  await dotenv.load(fileName: '.env');

  if (AppConfig.debugLogging) {
    print(AppConfig.getStatus());
  }

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
  late WebSocketChannel _channel;
  final TtsService _tts = TtsService();
  final StreamController<Map<String, dynamic>> _queue = StreamController();

  int _lastSpokenMs = 0;
  String _lastPhrase = '';
  bool _isSpeaking = false;
  bool _ready = false;
  bool _started = false;
  String _status = 'Initializing...';
  String _lastDetection = '';

  // Update per environment:
  // Android emulator : ws://10.0.2.2:8001/ws
  // iOS simulator    : ws://127.0.0.1:8001/ws
  // Web (local)      : ws://localhost:8001/ws
  // Real device      : ws://192.168.X.X:8001/ws

  static String get _wsUrl => AppConfig.websocketUrl;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _init());
  }

  Future<void> _init() async {
    try {
      await _tts.init();
      if (mounted) setState(() => _status = 'Ready');
      _connect();
      _processQueue();
      if (mounted) setState(() => _ready = true);
    } catch (e) {
      if (mounted) setState(() => _status = 'Init error: $e');
    }
  }

  void _connect() {
    try {
      _channel = WebSocketChannel.connect(Uri.parse(_wsUrl));
      _channel.stream.listen(
        _onMessage,
        onDone: () => Future.delayed(const Duration(seconds: 2), _connect),
        onError: (e) {
          print('WebSocket error: $e');
          Future.delayed(const Duration(seconds: 2), _connect);
        },
      );
    } catch (e) {
      print('Connection error: $e');
      Future.delayed(const Duration(seconds: 2), _connect);
    }
  }

  void _onMessage(dynamic raw) {
    if (!_started) return; // don't process until user has interacted
    final data = jsonDecode(raw as String) as Map<String, dynamic>;
    final urgency = data['urgency'] as String;
    final phrase = _buildPhrase(data);
    final now = DateTime.now().millisecondsSinceEpoch;
    final cooldown = urgency == 'high' ? 600 : 2000;

    if (now - _lastSpokenMs < cooldown) return;
    if (phrase == _lastPhrase && urgency != 'high') return;

    if (urgency == 'high' && _isSpeaking) {
      _tts.stop();
      _isSpeaking = false;
    }

    _lastSpokenMs = now;
    _lastPhrase = phrase;
    _queue.add(data);

    if (mounted) setState(() => _lastDetection = phrase);
  }

  void _processQueue() {
    _queue.stream
        .asyncMap((data) async {
          _isSpeaking = true;
          await _tts.synthesizeAndPlay(_buildPhrase(data));
          _isSpeaking = false;
        })
        .listen((_) {});
  }

  String _buildPhrase(Map<String, dynamic> d) {
    final label = d['label'] as String;
    final distance = (d['distance'] as num).toStringAsFixed(1);
    final direction = d['direction'] as String;
    final urgency = d['urgency'] as String;

    if (urgency == 'high') return 'Stop! $label very close, move $direction';
    if (urgency == 'medium')
      return '$label at $distance meters, move $direction';
    return '$label ahead, $distance meters';
  }

  Future<void> _onStart() async {
    await _tts.unlock();
    setState(() {
      _started = true;
      _status = 'Listening...';
    });
  }

  Color _urgencyColor(String phrase) {
    if (phrase.startsWith('Stop!')) return Colors.red.shade400;
    if (phrase.contains('meters, move')) return Colors.orange.shade400;
    return Colors.green.shade400;
  }

  @override
  void dispose() {
    _channel.sink.close();
    _tts.stop();
    _queue.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: _started ? _buildListeningScreen() : _buildStartScreen(),
      ),
    );
  }

  Widget _buildStartScreen() {
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

  Widget _buildListeningScreen() {
    final color = _lastDetection.isEmpty
        ? Colors.white24
        : _urgencyColor(_lastDetection);

    return Padding(
      padding: const EdgeInsets.all(32),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          // Status indicator dot
          AnimatedContainer(
            duration: const Duration(milliseconds: 300),
            width: 12,
            height: 12,
            decoration: BoxDecoration(color: color, shape: BoxShape.circle),
          ),
          const SizedBox(height: 32),

          // Last spoken phrase
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
          const SizedBox(height: 48),

          // Speaking indicator
          AnimatedOpacity(
            opacity: _isSpeaking ? 1.0 : 0.0,
            duration: const Duration(milliseconds: 200),
            child: const Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(Icons.volume_up, color: Colors.white38, size: 16),
                SizedBox(width: 6),
                Text(
                  'Speaking...',
                  style: TextStyle(color: Colors.white38, fontSize: 13),
                ),
              ],
            ),
          ),

          const Spacer(),

          // Stop button at the bottom
          TextButton(
            onPressed: () => setState(() {
              _started = false;
              _lastDetection = '';
              _status = 'Ready';
              _tts.stop();
            }),
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
