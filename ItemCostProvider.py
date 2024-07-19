import sys
import requests
import json
import os
import logging
from statistics import mean
import time
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel, QFileDialog, QMessageBox, QApplication, QStatusBar)
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QIcon

# Устанавливаем правильные пути, для корретной работы как из среды разработки, так и автономного ехе
def resource_path(relative_path):

    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

logging.basicConfig(level=logging.INFO)

# Константы

# Получить список предметов категории misc
GITHUB_API_URL = "https://api.github.com/repos/EXBO-Studio/stalcraft-database/contents/ru/items/misc"

# Получить карточку данных конкретного предмета
GITHUB_RAW_URL_TEMPLATE = "https://raw.githubusercontent.com/EXBO-Studio/stalcraft-database/main/ru/items/misc/{}"

# Получить аукционную историю предмета
AUCTION_API_URL_TEMPLATE = "https://eapi.stalcraft.net/ru/auction/{}/history"
CLIENT_ID = "39"
CLIENT_SECRET = "MnbRDI0XfVWPlbQLGAiBJhRc0zStS0HMeVVxgtKc"

#Deprecated
RU_LANG_FILE_PATH = "ru.lang"


class Item:
    def __init__(self, item_id, name_key):
        self.item_id = item_id
        self.name_key = name_key
        self.price_indicator = None
        self.average_price = None

# Получаем список всех предметов
def fetch_json_file_list():
    response = requests.get(GITHUB_API_URL)
    response.raise_for_status()
    return response.json()

# Получаем карточку предмета
def download_and_parse_json(file_name):
    url = GITHUB_RAW_URL_TEMPLATE.format(file_name)
    response = requests.get(url)
    response.raise_for_status()
    return response.json()

# Проверяем, используется ли предмет в крафтах
def contains_translation_label(json_data):
    for block in json_data.get("infoBlocks", []):
        for element in block.get("elements", []):
            if element.get("name", {}).get("lines", {}).get("ru") == "Используется для крафтов":
                return True
    return False

# Получаем аукционную историю
def fetch_auction_history(item_id):
    url = AUCTION_API_URL_TEMPLATE.format(item_id)
    headers = {
        "Client-Id": CLIENT_ID,
        "Client-Secret": CLIENT_SECRET
    }
    params = {
        "limit": 200
    }
    response = requests.get(url, headers=headers, params=params)
    response.raise_for_status()
    return response.json()

# Считаем среднюю цену предмета
def calculate_average_price(prices):
    return mean(prices) if prices else 0

# Изменяем файл локализации, используя ключи.
def update_ru_lang_file(file_path, items):
    with open(file_path, 'r+', encoding='utf-8') as file:
        lines = file.readlines()
        updated_lines = []
        for line in lines:
            for item in items:
                if item.name_key in line:
                    line = line.split('^')[0].strip()
                    line = f"{line}^(§{item.price_indicator} {item.average_price}руб.)\n"
                    logging.info(f"Edited line: {line.strip()}")
                    break
            updated_lines.append(line)
        file.seek(0)
        file.writelines(updated_lines)
        file.truncate()

# Поддержание UI и его динамичного изменения
class WorkerThread(QThread):
    progress = pyqtSignal(str)
    status_updated = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    finished = pyqtSignal()

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    def run(self):
        try:
            self.status_updated.emit("Fetching JSON file list...")
            json_files = fetch_json_file_list()
            self.progress.emit("fetched_items")

            items = []
            total_files = len(json_files)
            for index, file_info in enumerate(json_files):
                file_name = file_info["name"]
                self.status_updated.emit(f"Processing file: {file_name}")

                json_data = download_and_parse_json(file_name)

                if contains_translation_label(json_data):
                    item_id = json_data["id"]
                    name_key = json_data["name"]["key"]
                    items.append(Item(item_id, name_key))
                    self.status_updated.emit(f"Found item: {name_key}")


                self.progress.emit(f"filtered_crafting_items:{index + 1}/{total_files}")

            self.progress.emit("filtered_crafting_items:completed")

            total_items = len(items)
            for index, item in enumerate(items):
                self.status_updated.emit(f"Fetching auction history for item ID: {item.item_id}")

                for attempt in range(2):
                    try:
                        auction_data = fetch_auction_history(item.item_id)
                        prices = [entry["price"] / entry["amount"] for entry in auction_data["prices"]]
                        average_price = int(calculate_average_price(prices))
                        break
                    except requests.exceptions.RequestException as e:
                        if attempt == 1:
                            average_price = 0
                        else:
                            time.sleep(1)

                if average_price < 5000:
                    item.price_indicator = 7
                elif average_price < 20000:
                    item.price_indicator = 2
                elif average_price < 80000:
                    item.price_indicator = 5
                else:
                    item.price_indicator = 6
                item.average_price = average_price

                self.progress.emit(f"got_auction_history:{index + 1}/{total_items}")

            self.status_updated.emit(f"Updating {self.file_path}...")
            update_ru_lang_file(self.file_path, items)
            self.progress.emit("edited_lang_file")
        except Exception as e:
            self.error_occurred.emit(str(e))
        finally:
            self.finished.emit()

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowTitle("ItemCostProvider")
        self.setGeometry(100, 100, 600, 400)

        self.setWindowIcon(QIcon(resource_path("ItemCostProviderIcon.ico")))

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        self.file_label = QLabel("No file selected")
        layout.addWidget(self.file_label)

        self.select_button = QPushButton("Select File")
        self.select_button.clicked.connect(self.select_file)
        layout.addWidget(self.select_button)

        self.run_button = QPushButton("Run")
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self.run_app)
        layout.addWidget(self.run_button)

        # Step indicators
        self.step_labels = {
            'fetched_items': QLabel("Fetched items"),
            'filtered_crafting_items': QLabel("Filtered crafting items (0/0)"),
            'got_auction_history': QLabel("Processed auction history of item (0/0)"),
            'edited_lang_file': QLabel("Edited .lang file")
        }

        for label in self.step_labels.values():
            layout.addWidget(label)
            self.set_step_incomplete(label)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.footer = QLabel("Created by MyLittleVasya")
        layout.addWidget(self.footer)

    def set_step_complete(self, label):
        label.setStyleSheet("color: green;")
        label.setText(label.text().split(" - ")[0] + " - Completed")

    def set_step_incomplete(self, label):
        label.setStyleSheet("color: red;")
        label.setText(label.text().split(" - ")[0])

    def reset_steps(self):
        for label in self.step_labels.values():
            self.set_step_incomplete(label)

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select a .lang file", "", "Text files (*.lang)")
        if file_path:
            self.file_label.setText(f"Selected file: {file_path}")
            self.file_path = file_path
            self.run_button.setEnabled(True)

    def run_app(self):
        if not hasattr(self, 'file_path'):
            QMessageBox.warning(self, "No File Selected", "Please select a .lang file before running.")
            return

        self.reset_steps()
        self.thread = WorkerThread(self.file_path)
        self.thread.progress.connect(self.update_progress)
        self.thread.status_updated.connect(self.update_status)
        self.thread.error_occurred.connect(self.handle_error)
        self.thread.finished.connect(self.on_finished)
        self.thread.start()

    def update_progress(self, step_info):
        if "got_auction_history" in step_info:
            processed, total = map(int, step_info.split(":")[1].split("/"))
            self.step_labels['got_auction_history'].setText(f"Processed auction history of item ({processed}/{total})")
            if processed == total:
                self.set_step_complete(self.step_labels['got_auction_history'])
        elif "filtered_crafting_items" in step_info:
            if "completed" in step_info:
                self.set_step_complete(self.step_labels['filtered_crafting_items'])
            else:
                processed, total = map(int, step_info.split(":")[1].split("/"))
                self.step_labels['filtered_crafting_items'].setText(f"Filtered crafting items ({processed}/{total})")
                if processed == total:
                    self.set_step_complete(self.step_labels['filtered_crafting_items'])
        else:
            self.set_step_complete(self.step_labels.get(step_info, QLabel()))

    def update_status(self, status):
        self.status_bar.showMessage(status)

    def handle_error(self, error_message):
        QMessageBox.critical(self, "Error", f"An error occurred: {error_message}")

    def on_finished(self):
        self.status_bar.showMessage("Process completed")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    mainWin = MainWindow()
    mainWin.show()
    sys.exit(app.exec())
