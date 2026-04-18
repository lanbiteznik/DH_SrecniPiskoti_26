import 'dart:io';
import 'package:elevenlabs_flutter/elevenlabs_flutter.dart';
import 'package:elevenlabs_flutter/elevenlabs_config.dart';
import 'package:elevenlabs_flutter/elevenlabs_types.dart';
import 'package:just_audio/just_audio.dart';
import 'tts_interface.dart';
import '../config.dart';

class TtsService implements TtsInterface {
  final ElevenLabsAPI _api = ElevenLabsAPI();
  final AudioPlayer _player = AudioPlayer();
  bool _ready = false;

  @override
  Future<void> init() async {
    await _api.init(
      config: ElevenLabsConfig(
        apiKey: AppConfig.elevenLabsApiKey,
        baseUrl: 'https://api.elevenlabs.io',
      ),
    );
    _ready = true;
  }

  @override
  Future<void> synthesizeAndPlay(String text) async {
    if (!_ready) return;
    try {
      final File file = await _api.synthesize(
        TextToSpeechRequest(
          voiceId: AppConfig.elevenLabsVoiceId,
          text: text,
          modelId: 'eleven_turbo_v2',
          voiceSettings: VoiceSettings(similarityBoost: 0.75, stability: 0.50),
        ),
        optimizeStreamingLatency: 3,
      );
      await _player.setFilePath(file.path);
      await _player.play();
      await _player.processingStateStream.firstWhere(
        (s) => s == ProcessingState.completed,
      );
    } on TooManyRequestsException {
      return;
    } on NoInternetConnectionException {
      return;
    } catch (e) {
      print('TTS error: $e');
    }
  }

  @override
  Future<void> stop() async {
    await _player.stop();
  }

  @override
  Future<void> unlock() async {
    // No special unlock needed for mobile
  }
}
