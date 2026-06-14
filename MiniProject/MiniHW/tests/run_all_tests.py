import sys
import subprocess
import time


def check_server_alive(url="http://localhost:5000/status"):
    """בדיקה מהירה שהשרת אכן באוויר לפני שמתחילים להריץ את הטסטים"""
    try:
        import requests

        # פנייה ללא טוקן רק כדי לראות אם יש שרת שמגיב (מצפים ל-401 או 200, העיקר שלא תהיה שגיאת חיבור)
        requests.get(url, timeout=2)
        return True
    except Exception:
        return False


def run_tests():
    print("=" * 60)
    print("🚀 Starting PictureServer Test Automation Suite")
    print("=" * 60)

    # 1. בדיקה שהשרת מופעל בתוך ה-Docker
    if not check_server_alive():
        print("❌ Error: Target server on localhost:5000 is not responding.")
        print("👉 Please make sure your server is running (e.g., 'docker-compose up').")
        sys.exit(1)

    print("✅ Target server is alive. Launching test files...\n")
    time.sleep(1)

    # 2. רשימת קבצי הטסטים להרצה לפי סדר לוגי הגיוני
    test_files = [
        "test_unit_endpoints.py",  # בדיקות יחידה בסיסיות לכל נתיב
        "test_integration_flow.py",  # בדיקת זרימת משתמש מורכבת
        "test_security_auth.py",  # בדיקות חסימת אבטחה וטוקנים מזויפים
        "test_system_complete_use.py",  # בדיקת מערכת מלאה כולל מסווג ומונים
        "test_stress_basic_load.py",  # בדיקת עומס מקבילי קלה
    ]

    all_passed = True
    summary = {}

    # 3. הרצת כל קובץ בנפרד בעזרת pytest
    for test_file in test_files:
        print(# סגנון הדפסה נקי וברור לכל שלב
            f"🏃 Running: {test_file}...",
            flush=True,
        )

        # הפעלת pytest כתהליך בן (subprocess) עם דגל -v לפירוט
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-v", test_file],
            capture_output=False,  # נציג את הפלט ישירות על המסך בזמן אמת
        )

        if result.returncode == 0:
            summary[test_file] = "🟢 PASSED"
        else:
            summary[test_file] = "🔴 FAILED"
            all_passed = False

        print("-" * 60)

    # 4. הדפסת דוח סיכום סופי ומעוצב
    print("\n" + "=" * 60)
    print("📊 FINAL TEST AUTOMATION SUMMARY")
    print("=" * 60)
    for file, status in summary.items():
        print(f"{file:<30} -> {status}")
    print("=" * 60)

    if all_passed:
        print("🎉 SUCCESS: All tests passed successfully! Your server is compliant.")
        sys.exit(0)
    else:
        print("💥 FAILURE: Some tests failed. Please check the logs above.")
        sys.exit(1)


if __name__ == "__main__":
    run_tests()