import 'package:flutter_dotenv/flutter_dotenv.dart';

/// Configuration class for managing environment variables
class AppConfig {
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

  /// Validate that all required environment variables are set
  static bool get isValid {
    return elevenLabsApiKey != 'NOT_SET' &&
        elevenLabsVoiceId != 'NOT_SET' &&
        websocketUrl.isNotEmpty;
  }

  /// Get a status string with configuration summary
  static String getStatus() {
    return '''
Vision Assistant Configuration:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔑 ElevenLabs API Key: ${elevenLabsApiKey.substring(0, 10)}...
🎙️  Voice ID: $elevenLabsVoiceId
📡 WebSocket: $websocketUrl
🌍 Environment: $environment
🐛 Debug Logging: $debugLogging
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ''';
  }
}
