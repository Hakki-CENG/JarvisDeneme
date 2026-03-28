# Jarvis-X

Windows için tam erişimli (onay kapılı) masaüstü ajan sistemi.

## Bileşenler
- `backend/`: FastAPI tabanlı çok-ajan orkestratör, risk/onay kapısı, desktop action engine, self-improvement, skill registry.
- `frontend/`: Canlı görev paneli, onay merkezi, quota monitörü, safety kill-switch, skill çalıştırma ekranı.

## Hızlı Başlangıç

### Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
python -m playwright install chromium
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

### Windows PowerShell Shortcut
```powershell
./scripts/start_backend.ps1
./scripts/start_frontend.ps1
```

Panel: `http://localhost:5173`
API: `http://localhost:8000`

İlk açılışta backend, `.jarvisx_data/INITIAL_ADMIN_TOKEN.txt` dosyasına başlangıç admin token üretir.
Frontend panelde `Authentication` bölümüne bu tokeni gir.
Token döndürmek için `POST /auth/bootstrap` çağrısında mevcut admin tokeni `X-API-Key` olarak gönder.

## Ana API Uçları
- `POST /auth/bootstrap`
- `GET /auth/me`
- `POST /tasks`
- `POST /tasks/plan`
- `POST /tasks/verify`
- `GET /tasks/{id}`
- `POST /tasks/{id}/resume`
- `POST /tasks/{id}/cancel`
- `GET /checkpoints/{task_id}`
- `GET /world-state/{task_id}`
- `GET /events`
- `POST /memory/add`
- `POST /memory/search`
- `GET /memory/recent`
- `POST /approvals/{id}`
- `POST /desktop/actions`
- `POST /desktop/rollback`
- `GET /models/quotas`
- `POST /self-improve/run`
- `GET /self-improve/report/{id}`
- `GET /skills`, `POST /skills/register`, `POST /skills/run`
- `GET /safety/status`, `POST /safety/emergency-stop`, `POST /safety/emergency-clear`
- `POST /voice/transcribe`, `POST /voice/transcribe-mic`, `POST /voice/speak`, `POST /voice/parse-command`
- `POST /vision/ocr`, `POST /vision/ocr-layout`, `POST /vision/analyze`
- `GET /metrics`
- `GET /audit/logs`
- `WS /ws/live`

## Güvenlik Davranışı
- Kritik eylemler (silme/kurulum/sistem değişikliği) onaysız çalışmaz.
- Emergency stop tüm aktif ajan eylemlerini keser.
- Secret vault yerelde şifreli saklama sağlar (`backend/.jarvisx_data`).
- Tüm API çağrıları `X-API-Key` gerektirir (bootstrap hariç).
- Rate limit ve audit log aktif.
- `Idempotency-Key` header ile task oluşturma idempotent çalışır.
- Shell ve dosya işlemleri policy motorundan geçer.
- Shell tarafında komut zinciri segment bazlı denetlenir (`&&`, `;`, `|` kaçakları).
- HTTP request aksiyonları URL/method policy kontrolünden geçer.
- Dosya yaz/sil/taşıma işlemleri rollback snapshot metadata üretir.
- Event akışı hem websocket hem kalıcı event store üzerinden izlenebilir.
- Görev sonuçları uzun dönem hafızaya yazılır ve planner bu hafızayı tekrar kullanır.

## Test
```bash
cd backend
pytest -q
```

## Not
Bu repo üretim-hardening öncesi güçlü bir v1 iskeletidir. Canlı kullanımda Windows-specific bağımlılıkları (`pywin32`, `pyautogui`, OCR/TTS paketleri) tam kurulumla doğrulayın.
