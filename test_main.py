import sys
import logging

# Konfiguracja logowania
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Import PyQt5
from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel


def main():
    """Uproszczona wersja main do testów"""
    logger.info("Starting simplified test app")

    # Inicjalizacja aplikacji
    app = QApplication(sys.argv)

    # Utworzenie prostego okna
    window = QMainWindow()
    window.setWindowTitle("Test App")
    window.setGeometry(100, 100, 400, 300)

    # Dodanie etykiety
    label = QLabel("Test application", window)
    label.setGeometry(100, 100, 200, 50)

    # Wyświetlenie okna
    window.show()

    # Uruchomienie pętli zdarzeń
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()