# ModMind AI Android

Native Android client (Kotlin + Jetpack Compose) for the existing ModMind FastAPI backend hosted on Render.

## Build
The GitHub Actions workflow builds `app-debug.apk` automatically. No API key is included in the APK.

## Connect to Render
Open app settings and paste the public HTTPS URL of the existing Render web service, for example `https://your-service.onrender.com`. Do not add a trailing slash. The app stores this URL locally.

The Android client calls:
- `POST /api/plan`
- `GET /api/search`
- `POST /api/build`

Gemini credentials remain only in the Render environment as `GEMINI_API_KEY`.
