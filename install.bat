@echo off
echo Creating Python virtual environment...
python -m venv venv

echo Activating virtual environment...
call venv\Scripts\activate

echo Upgrading pip...
python -m pip install --upgrade pip

echo Installing backend dependencies...
cd backend
pip install -e .
cd ..

echo Installing frontend dependencies...
cd frontend
call npm install
cd ..

echo Installation complete.
pause
