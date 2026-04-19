import 'dart:async';
import 'dart:html' as html;
import 'dart:typed_data';
import 'package:http/http.dart' as http;
import 'dart:convert';
import 'config.dart';
import 'dart:js_util' as js_util;

class SttService {
  html.MediaRecorder? _recorder;
  html.MediaStream? _stream;
  final List<html.Blob> _chunks = [];
  bool _isListening = false;
  bool _isTranscribing = false; // prevent double calls

  static const _triggers = [
    'where is',
    "where's",
    'where are',
    'find',
    'locate',
    'look for',
    'search for',
    'wheres',
    'wears',
    'wares',
  ];

  static const _fillers = [
    'the',
    'a',
    'an',
    'my',
    'that',
    'this',
    'some',
    'any',
    'those',
    'these',
    'its',
    'their',
    'our',
    'your',
    'her',
    'his',
    'me',
    'please',
    'now',
  ];

  Future<void> init() async {
    print('[STT] ElevenLabs STT ready');
  }

  bool get isListening => _isListening;

  Future<void> startListening() async {
    if (_isListening || _isTranscribing) {
      print('[STT] Already active, skipping startListening');
      return;
    }
    _chunks.clear();

    try {
      _stream = await html.window.navigator.mediaDevices!
          .getUserMedia({'audio': true, 'video': false});

      _recorder = html.MediaRecorder(_stream!);
      _recorder!.addEventListener('dataavailable', (event) {
        final blob = (event as html.BlobEvent).data;
        if (blob != null && blob.size > 0) {
          _chunks.add(blob);
          print('[STT] Chunk received: ${blob.size} bytes');
        }
      });

      _recorder!.start();
      _isListening = true;
      print('[STT] Recording started');
    } catch (e) {
      print('[STT] Start error: $e');
    }
  }

  Future<String?> stopAndTranscribe() async {
    print(
        '[STT] stopAndTranscribe called — listening=$_isListening recorder=$_recorder');

    if (!_isListening || _recorder == null) {
      print('[STT] Not recording, aborting transcribe');
      return null;
    }

    _isListening = false;
    _isTranscribing = true;

    // Stop recorder and wait for final data chunk
    final stopCompleter = Completer<void>();
    _recorder!.addEventListener('stop', (_) {
      print('[STT] Recorder stopped');
      if (!stopCompleter.isCompleted) stopCompleter.complete();
    });
    _recorder!.stop();

    // Timeout in case stop event never fires
    await stopCompleter.future.timeout(
      const Duration(seconds: 3),
      onTimeout: () => print('[STT] Stop timeout'),
    );

    _stream?.getTracks().forEach((t) => t.stop());
    _stream = null;

    print('[STT] Chunks collected: ${_chunks.length}');

    if (_chunks.isEmpty) {
      print('[STT] No audio recorded');
      _isTranscribing = false;
      return null;
    }

    final blob = html.Blob(_chunks, 'audio/webm');
    print('[STT] Blob size: ${blob.size}');
    final bytes = await _blobToBytes(blob);
    if (bytes == null) {
      print('[STT] Failed to read blob');
      _isTranscribing = false;
      return null;
    }

    print('[STT] Sending ${bytes.length} bytes to ElevenLabs...');
    final transcript = await _transcribe(bytes);
    _isTranscribing = false;

    if (transcript == null) return null;

    print('[STT] Transcript: $transcript');
    final object = _extractObject(transcript.toLowerCase().trim());
    print('[STT] Extracted object: $object');
    return object;
  }

  Future<Uint8List?> _blobToBytes(html.Blob blob) async {
    final completer = Completer<Uint8List?>();
    final reader = html.FileReader();

    reader.onLoadEnd.listen((_) {
      if (reader.readyState == html.FileReader.DONE) {
        try {
          // Use dartify to convert JS ArrayBuffer to Dart ByteBuffer
          final buffer = reader.result as dynamic;
          final dartBuffer = js_util.dartify(buffer);
          if (dartBuffer is ByteBuffer) {
            completer.complete(dartBuffer.asUint8List());
          } else if (dartBuffer is Uint8List) {
            completer.complete(dartBuffer);
          } else {
            // Last resort: use the blob URL approach instead
            _blobToBytesViaUrl(blob).then(completer.complete);
          }
        } catch (e) {
          print('[STT] Blob convert error: $e');
          _blobToBytesViaUrl(blob).then(completer.complete);
        }
      }
    });

    reader.readAsArrayBuffer(blob);
    return completer.future;
  }

// Fallback: fetch blob via object URL — always works on web
  Future<Uint8List?> _blobToBytesViaUrl(html.Blob blob) async {
    final url = html.Url.createObjectUrlFromBlob(blob);
    try {
      final response = await http.get(Uri.parse(url));
      if (response.statusCode == 200) return response.bodyBytes;
      return null;
    } catch (e) {
      print('[STT] URL fetch error: $e');
      return null;
    } finally {
      html.Url.revokeObjectUrl(url);
    }
  }

  Future<String?> _transcribe(Uint8List audioBytes) async {
    try {
      final request = http.MultipartRequest(
        'POST',
        Uri.parse('https://api.elevenlabs.io/v1/speech-to-text'),
      );

      request.headers['xi-api-key'] = AppConfig.elevenLabsApiKey;
      request.files.add(http.MultipartFile.fromBytes(
        'file',
        audioBytes,
        filename: 'audio.webm',
      ));
      request.fields['model_id'] = 'scribe_v1';
      // Give the model context so it transcribes navigation commands accurately
      request.fields['tag_audio_events'] = 'false';
      request.fields['language_code'] = 'en';

      final response = await request.send();
      final body = await response.stream.bytesToString();
      print('[STT] API response ${response.statusCode}: $body');

      if (response.statusCode == 200) {
        final data = jsonDecode(body) as Map<String, dynamic>;
        final text = data['text'] as String?;
        return text;
      } else {
        print('[STT] API error: ${response.statusCode} $body');
        return null;
      }
    } catch (e) {
      print('[STT] Transcribe error: $e');
      return null;
    }
  }

  Future<void> stop() async {
    _isListening = false;
    _isTranscribing = false;
    try {
      _recorder?.stop();
    } catch (_) {}
    _stream?.getTracks().forEach((t) => t.stop());
    _stream = null;
    _recorder = null;
  }

  String? _extractObject(String transcript) {
    // Clean punctuation before processing
    final cleaned = transcript.replaceAll(RegExp(r'[^\w\s]'), '').trim();

    for (final trigger in _triggers) {
      final idx = cleaned.indexOf(trigger);
      if (idx != -1) {
        var after = cleaned.substring(idx + trigger.length).trim();

        bool stripped = true;
        while (stripped) {
          stripped = false;
          for (final filler in _fillers) {
            if (after == filler) return null;
            if (after.startsWith('$filler ')) {
              after = after.substring(filler.length).trim();
              stripped = true;
            }
          }
        }

        if (after.isNotEmpty) return after;
      }
    }
    return null;
  }
}
