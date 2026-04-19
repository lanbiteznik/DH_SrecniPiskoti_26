import 'dart:typed_data';
import 'dart:html' as html;
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'tts_interface.dart';
import '../config.dart';

class TtsService implements TtsInterface {
  bool _ready = false;
  html.AudioElement? _audio;
  int _generation = 0;

  @override
  Future<void> init() async {
    if (!AppConfig.isValid) return;
    _ready = true;
    print('[TTS] Web TTS ready');
  }

  // Just stops the audio element, does NOT increment generation
  void _stopAudio() {
    if (_audio != null) {
      _audio!.pause();
      _audio!.src = '';
      _audio = null;
    }
  }

  @override
  Future<void> synthesizeAndPlay(String text) async {
    if (!_ready) return;

    final gen = ++_generation;

    try {
      final response = await http.post(
        Uri.parse(
          'https://api.elevenlabs.io/v1/text-to-speech'
          '/${AppConfig.elevenLabsVoiceId}/stream'
          '?optimize_streaming_latency=4',
        ),
        headers: {
          'xi-api-key': AppConfig.elevenLabsApiKey,
          'Content-Type': 'application/json',
          'Accept': 'audio/mpeg',
        },
        body: jsonEncode({
          'text': text,
          'model_id': 'eleven_turbo_v2',
          'voice_settings': {
            'similarity_boost': 0.75,
            'stability': 0.50,
          },
        }),
      );

      if (gen != _generation) return; // cancelled while fetching

      if (response.statusCode != 200) {
        print('[TTS] API error: ${response.statusCode}');
        return;
      }

      final blob = html.Blob(
        [Uint8List.fromList(response.bodyBytes)],
        'audio/mpeg',
      );
      final url = html.Url.createObjectUrlFromBlob(blob);

      _stopAudio(); // stop previous audio WITHOUT touching generation

      if (gen != _generation) {
        // check again after stopping
        html.Url.revokeObjectUrl(url);
        return;
      }

      _audio = html.AudioElement(url);
      await _audio!.play();
      await _audio!.onEnded.first;
      html.Url.revokeObjectUrl(url);
    } catch (e) {
      print('TTS web error: $e');
    }
  }

  @override
  Future<void> stop() async {
    _generation++; // cancels any in-flight request
    _stopAudio();
  }

  @override
  Future<void> unlock() async {
    try {
      final audio = html.AudioElement()
        ..src = 'data:audio/wav;base64,'
            'UklGRiQAAABXQVZFZm10IBAAAA'
            'EAAQAAgD4AAAB9AAACABAAAA=='
        ..volume = 0;
      await audio.play();
    } catch (_) {}
  }
}
