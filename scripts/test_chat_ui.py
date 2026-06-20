import sys
import os
import json
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import QUrl, QObject, Slot, Signal
from PySide6.QtWebChannel import QWebChannel

class Bridge(QObject):
    def __init__(self):
        super().__init__()

    @Slot(str)
    def sendMessage(self, message):
        print(f"User sent: {message}")

    @Slot(str)
    def log(self, text):
        print(f"WEB LOG: {text}")

class ChatWindow(QMainWindow):
    def __init__(self, html_path):
        super().__init__()
        self.setWindowTitle("PyLog Chat UI Test")
        self.resize(800, 700)

        self.browser = QWebEngineView()
        self.bridge = Bridge()
        self.channel = QWebChannel()
        self.channel.registerObject('bridge', self.bridge)
        self.browser.page().setWebChannel(self.channel)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.browser)
        self.setCentralWidget(container)

        # 加载 HTML
        abs_path = os.path.abspath(html_path)
        self.browser.setUrl(QUrl.fromLocalFile(abs_path))
        self.browser.loadFinished.connect(self.on_load)

    def on_load(self):
        print("Page loaded")
        # 注入测试数据
        test_tasks = [
            {"id": "1", "text": "分析数据结构", "status": "completed"},
            {"id": "2", "text": "生成可视化图表", "status": "in_progress"},
            {"id": "3", "text": "导出分析报告", "status": "pending"},
            {"id": "4", "text": "验证系统完整性", "status": "pending"}
        ]
        test_summary = "正在进行数据分析流程..."
        
        js_code = f"""
            if (typeof updateTopTodoList === 'function') {{
                updateTopTodoList({json.dumps(test_tasks)}, "{test_summary}");
                console.log("Injected test tasks");
            }} else {{
                console.error("updateTopTodoList not found");
            }}
        """
        self.browser.page().runJavaScript(js_code)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 获取模板路径
    html_file = os.path.join(os.path.dirname(__file__), "..", "plugins", "ai_assistant", "ui", "resources", "chat_template.html")
    
    window = ChatWindow(html_file)
    window.show()
    sys.exit(app.exec())
