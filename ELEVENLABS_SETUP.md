# ElevenLabs Text-to-Speech Setup Guide

The Vision Assistant app now uses **ElevenLabs** for professional-quality voice synthesis instead of the basic flutter_tts.

## 🎙️ ElevenLabs Benefits

- **Natural-sounding voices**: High-quality neural TTS
- **Multiple voices**: Choose from different voice profiles
- **Better pronunciation**: Handles complex words correctly
- **Professional quality**: Suitable for production use

---

## 📋 Setup Steps

### **Step 1: Create ElevenLabs Account**

1. Go to https://elevenlabs.io
2. Sign up for a free account
3. You get **10,000 free characters/month**

### **Step 2: Get Your API Key**

1. Log in to ElevenLabs dashboard
2. Go to **Account Settings** → **API keys**
3. Copy your API key

### **Step 3: Update Flutter App**

Edit [front_vision_assistant/lib/main.dart](front_vision_assistant/lib/main.dart#L21-L23):

```dart
// Replace sk_fb5c6906b2b54b2980ea963b95fa973489c7c34727142ec5 with your actual key
static const String elevenLabsApiKey = 'sk_1234567890abcdef...'; // Your API key here
static const String elevenLabsVoiceId = 'EXAVITQu4EsNXjluf0k5'; // Voice ID (Bella)
```

### **Step 4: Optional - Change Voice**

Available voices and their IDs:

| Voice | ID | Gender | Character |
|-------|----|---------|-|
| Bella | `EXAVITQu4EsNXjluf0k5` | Female | Warm, friendly |
| Daniel | `nPczCjzI2devNBz1zQrb` | Male | Deep, professional |
| Ava | `EXAVITQu4EsNXjluf0k5` | Female | Clear, energetic |
| David | `ZQRVWaI2sT9TI4YIBV4G` | Male | Calm, clear |
| Maria | `EXAVITQu4EsNXjluf0k5` | Female | Natural, expressive |

To use a different voice, just change `elevenLabsVoiceId`:

```dart
static const String elevenLabsVoiceId = 'nPczCjzI2devNBz1zQrb'; // Use Daniel voice
```

---

## 🚀 Usage

The app now:

1. **Receives proximity data** from WebSocket server
2. **Generates text prompt**: "Stop! Person very close, move left"
3. **Sends to ElevenLabs API**: Gets high-quality audio
4. **Plays audio**: User hears the voice alert

### **Console Output**

When running, you'll see:

```
🔊 Sending to ElevenLabs: "Stop! Person very close, move left"
✅ Audio received from ElevenLabs (1234 bytes)
📻 Playing audio...
```

---

## 🔧 Audio Playback

The current implementation receives audio from ElevenLabs but doesn't play it yet. To add audio playback:

### Option 1: Use `audioplayers` Package (Recommended)

```bash
flutter pub add audioplayers
```

Then update [main.dart](front_vision_assistant/lib/main.dart) to play the audio:

```dart
Future<void> _speakWithElevenLabs(String text) async {
    // ... existing code ...
    
    if (response.statusCode == 200) {
      final audioPlayer = AudioPlayer();
      await audioPlayer.playBytes(response.bodyBytes);
      print('✅ Audio playing...');
    }
}
```

### Option 2: Save Audio to File and Play

```dart
import 'dart:io';

if (response.statusCode == 200) {
  final file = File('audio.mp3');
  await file.writeAsBytes(response.bodyBytes);
  // Play file
}
```

---

## 💰 Pricing & Limits

**Free Tier:**
- 10,000 characters/month
- Standard voices
- Good for testing

**Pro Plan:**
- $5-$99/month
- More characters
- Priority support

---

## 🐛 Troubleshooting

### "Error: ElevenLabs API key not set!"
→ Replace `sk_fb5c6906b2b54b2980ea963b95fa973489c7c34727142ec5` with your actual key

### "401 Unauthorized"
→ Your API key is incorrect or expired

### "400 Bad Request"
→ Check text format or model_id spelling

### No audio playing
→ Install `audioplayers` package to enable audio playback

---

## 📝 Customization

### Adjust Voice Settings

In `_speakWithElevenLabs()`, modify:

```dart
'voice_settings': {
  'stability': 0.5,        // 0.0-1.0 (lower = more variation)
  'similarity_boost': 0.75, // 0.0-1.0 (higher = closer to voice)
},
```

### Change Model

Available models:
- `eleven_monolingual_v1` (faster, smaller files)
- `eleven_multilingual_v2` (supports multiple languages)

---

## 🌐 API Reference

**Endpoint:**
```
POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}
```

**Headers:**
```
Content-Type: application/json
xi-api-key: YOUR_API_KEY
```

**Request Body:**
```json
{
  "text": "Stop! Person very close, move left",
  "model_id": "eleven_monolingual_v1",
  "voice_settings": {
    "stability": 0.5,
    "similarity_boost": 0.75
  }
}
```

**Response:**
- `200 OK`: Audio file (MP3 bytes)
- `400 Bad Request`: Invalid input
- `401 Unauthorized`: Invalid API key
- `429 Too Many Requests`: Rate limit exceeded

---

## ✅ Next Steps

1. Get your ElevenLabs API key
2. Update the API key in main.dart
3. Install `audioplayers` for audio playback
4. Test with the test server
5. Enjoy professional voice alerts! 🎤
