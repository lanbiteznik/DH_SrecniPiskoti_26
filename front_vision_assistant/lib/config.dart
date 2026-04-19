import 'package:flutter_dotenv/flutter_dotenv.dart';

class AppConfig {
  static bool _loaded = false; // add this

  // add this method
  static Future<void> load() async {
    if (_loaded) return;
    await dotenv.load(fileName: '.env');
    _loaded = true;
  }

  // ElevenLabs configuration
  static String get elevenLabsApiKey =>
      dotenv.env['ELEVENLABS_API_KEY'] ?? 'NOT_SET';
  static String get elevenLabsVoiceId =>
      dotenv.env['ELEVENLABS_VOICE_ID'] ?? 'NOT_SET';

  // Base URL of the detection backend.
  // Same network: http://192.168.1.42:8001
  // Over internet: https://xxxx.ngrok-free.app
  static String get backendUrl =>
      (dotenv.env['BACKEND_URL'] ?? 'http://localhost:8001').trimRight('/');

  // REST search endpoint
  static String get searchUrl => '$backendUrl/search';

  // WebSocket URL derived from backendUrl (http→ws, https→wss)
  static String get websocketUrl =>
      '${backendUrl.replaceFirst(RegExp(r'^http'), 'ws')}/ws';

  // Environment configuration
  static String get environment => dotenv.env['ENVIRONMENT'] ?? 'development';

  // Feature flags
  static bool get debugLogging =>
      dotenv.env['DEBUG_LOGGING']?.toLowerCase() == 'true';

  static bool get isValid {
    return elevenLabsApiKey != 'NOT_SET' &&
        elevenLabsVoiceId != 'NOT_SET' &&
        backendUrl.isNotEmpty;
  }

  static String getStatus() {
    final keyPreview = elevenLabsApiKey.length >= 10
        ? '${elevenLabsApiKey.substring(0, 10)}...'
        : elevenLabsApiKey;

    return '''
Vision Assistant Configuration:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ElevenLabs API Key: $keyPreview
Voice ID: $elevenLabsVoiceId
Backend: $backendUrl
Environment: $environment
Debug Logging: $debugLogging
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ''';
  }
}
