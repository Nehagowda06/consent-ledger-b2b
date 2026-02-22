cd /d "%USERPROFILE%\consent-ledger-b2b"
echo ===== BLOCK 1: API layout =====
dir /b "apps\api"
dir /b "apps\api\app" 2>nul
dir /b "apps\api\alembic" 2>nul

echo ===== BLOCK 2: Main app + router wiring =====
type "apps\api\main.py" 2>nul
type "apps\api\app\main.py" 2>nul
findstr /s /n /i /c:"include_router(" /c:"APIRouter(" "apps\api\*.py"

echo ===== BLOCK 3: Model files + contents =====
dir /b /s apps\api\models\*.py 2>nul
dir /b /s apps\api\app\models\*.py 2>nul
for %%f in (apps\api\models\*.py apps\api\app\models\*.py) do @if exist "%%f" (echo ---- %%f ---- & type "%%f")

echo ===== BLOCK 4: Router files + contents =====
dir /b /s apps\api\routers\*.py 2>nul
dir /b /s apps\api\app\routers\*.py 2>nul
dir /b /s apps\api\app\api\*.py 2>nul
for %%f in (apps\api\routers\*.py apps\api\app\routers\*.py apps\api\app\api\*.py) do @if exist "%%f" (echo ---- %%f ---- & type "%%f")

echo ===== BLOCK 5: Alembic state =====
type "apps\api\alembic.ini" 2>nul
type "apps\api\alembic\env.py" 2>nul
dir /b "apps\api\alembic\versions" 2>nul
findstr /n /i /c:"revision =" /c:"down_revision =" "apps\api\alembic\versions\*.py" 2>nul
