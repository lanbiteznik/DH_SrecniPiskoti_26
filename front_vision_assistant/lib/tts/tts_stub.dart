import 'tts_interface.dart';

class TtsService implements TtsInterface {
  @override
  Future<void> init() async {}
  @override
  Future<void> synthesizeAndPlay(String text) async {}
  @override
  Future<void> stop() async {}
  @override
  Future<void> unlock() async {}
}
