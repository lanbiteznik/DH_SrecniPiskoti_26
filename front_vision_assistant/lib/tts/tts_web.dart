import 'dart:typed_data';
// ignore: avoid_web_libraries_in_flutter
import 'dart:html' as html;
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'tts_interface.dart';
import '../config.dart';

class TtsService implements TtsInterface {
  bool _ready = false;
  html.AudioElement? _audio;
  @override
  Future<void> unlock() async {
    try {
      final audio = html.AudioElement()
        ..src =
            'data:audio/wav;base64,'
            'UklGRiQAAABXQVZFZm10IBAAAA'
            'EAAQAAgD4AAAB9AAACABAAAA=='
        ..volume = 0;
      await audio.play();
    } catch (_) {}
  }

  @override
  Future<void> init() async {
    _ready = true; // no async setup needed for web
  }

  @override
  Future<void> synthesizeAndPlay(String text) async {
    if (!_ready) return;
    try {
      final response = await http.post(
        Uri.parse(
          'https://api.elevenlabs.io/v1/text-to-speech/${AppConfig.elevenLabsVoiceId}/stream'
          '?optimize_streaming_latency=3',
        ),
        headers: {
          'xi-api-key': AppConfig.elevenLabsApiKey,
          'Content-Type': 'application/json',
          'Accept': 'audio/mpeg',
        },
        body: jsonEncode({
          'text': text,
          'model_id': 'eleven_turbo_v2',
          'voice_settings': {'similarity_boost': 0.75, 'stability': 0.50},
        }),
      );

      if (response.statusCode != 200) return;

      // Convert bytes to a blob URL and play via <audio>
      final blob = html.Blob([
        Uint8List.fromList(response.bodyBytes),
      ], 'audio/mpeg');
      final url = html.Url.createObjectUrlFromBlob(blob);

      await stop(); // stop any currently playing audio
      _audio = html.AudioElement(url);
      await _audio!.play();

      // Wait for playback to finish then revoke the blob URL
      await _audio!.onEnded.first;
      html.Url.revokeObjectUrl(url);
    } catch (e) {
      print('TTS web error: $e');
    }
  }

  @override
  Future<void> stop() async {
    if (_audio != null) {
      _audio!.pause();
      _audio!.src = '';
      _audio = null;
    }
  }
}
