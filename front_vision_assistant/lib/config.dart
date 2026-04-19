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

  // WebSocket configuration
  static String get websocketUrl =>
      dotenv.env['WEBSOCKET_URL'] ?? 'ws://localhost:8001/ws';

  // Environment configuration
  static String get environment => dotenv.env['ENVIRONMENT'] ?? 'development';

  // Feature flags
  static bool get debugLogging =>
      dotenv.env['DEBUG_LOGGING']?.toLowerCase() == 'true';

  static bool get isValid {
    return elevenLabsApiKey != 'NOT_SET' &&
        elevenLabsVoiceId != 'NOT_SET' &&
        websocketUrl.isNotEmpty;
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
WebSocket: $websocketUrl
Environment: $environment
Debug Logging: $debugLogging
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ''';
  }
}
