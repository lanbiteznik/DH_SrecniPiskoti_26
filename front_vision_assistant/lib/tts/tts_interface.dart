abstract class TtsInterface {
  Future<void> init();
  Future<void> synthesizeAndPlay(String text);
  Future<void> stop();
  Future<void> unlock(); // called once on first user gesture
}
