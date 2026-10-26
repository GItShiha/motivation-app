"""Компактная памятка по намерениям реализации; не создаёт планы автоматически."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel, QPushButton, QWidget, QLayout
from PySide6.QtCore import Qt

EXAMPLES = [
    ('Прокрастинация', 'я замечаю, что откладываю начало работы',
     'открываю один тикет и начинаю его обрабатывать'),
    ('Отвлечения', 'во время работы я открыл развлекательный сайт',
     'закрываю вкладку и возвращаюсь к текущему тикету'),
    ('Возвращение после перерыва', 'мой рабочий перерыв закончился',
     'я открываю CRM и приступаю к следующему обращению'),
    ('Усталость', 'я замечаю, что теряю концентрацию',
     'во время разрешённого перерыва встаю и немного прохожусь'),
    ('Думскроллинг', 'я ловлю себя на бесцельном пролистывании ленты',
     'закрываю её и выбираю одно осознанное действие'),
]


def text(value, role=None):
    item = QLabel(value)
    item.setTextFormat(Qt.TextFormat.PlainText)
    item.setWordWrap(True)
    if role:
        item.setObjectName(role)
    return item


class IntentionsGuide(QFrame):
    example_selected = Signal(str, str)
    state_changed = Signal()

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.setObjectName('card')
        layout = QVBoxLayout(self)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        layout.addWidget(text('Намерения реализации', 'section'))
        layout.addWidget(text('Короткая памятка · Implementation Intentions', 'subtitle'))
        self.toggle = QPushButton()
        self.toggle.setCheckable(True)
        self.toggle.setChecked(settings.get('visible', False))
        self.toggle.setAccessibleName('Показать или скрыть гайд по намерениям реализации')
        layout.addWidget(self.toggle)
        self.contents = QWidget()
        body = QVBoxLayout(self.contents)
        body.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        body.setContentsMargins(0, 4, 0, 0)
        body.setSpacing(10)
        self.sections = {}
        self.example_buttons = []
        overview = self.section(body, 'what', '01 · Что такое «Если → то»?', True)
        overview.addWidget(text('Это заранее составленный план, связывающий конкретную ситуацию или сигнал с определённым действием.'))
        overview.addWidget(text('ЕСЛИ [конкретная ситуация], ТО [конкретное действие].', 'section'))
        overview.addWidget(text('План помогает не принимать одно и то же решение заново и меньше полагаться исключительно на силу воли. Он поддерживает начало действия, но не гарантирует результат.'))
        steps = self.section(body, 'how', '02 · Как составить работающий план')
        steps.addWidget(text('1. Выберите конкретный, узнаваемый сигнал: время, событие, мысль, чувство или действие.\n\n2. Назначьте одно простое, выполнимое действие.\n\n3. Сформулируйте: «Если X, то я сделаю Y».\n\n4. Мысленно представьте ситуацию и своё действие.\n\n5. Если план не срабатывает, уточните сигнал или упростите действие.'))
        steps.addWidget(text('Неудачно: «Если мне не хочется работать, то я стану продуктивным». «Стать продуктивным» — пожелание, а не понятный первый шаг.', 'subtitle'))
        steps.addWidget(text('Удачно: «Если я замечаю, что откладываю работу, то открываю первый тикет». Есть узнаваемый сигнал и конкретное выполнимое действие.'))
        examples = self.section(body, 'examples', '03 · Примеры — перенесите в свой план')
        examples.addWidget(text('Выберите пример, затем адаптируйте его к своей ситуации в форме выше. План сохранится только после нажатия «Добавить план».', 'subtitle'))
        for category, trigger, action in EXAMPLES:
            examples.addWidget(text(category, 'section'))
            examples.addWidget(text(f'Если {trigger}, то {action}.'))
            use = QPushButton('Использовать пример')
            use.setAccessibleName(f'Использовать пример: {category}')
            use.clicked.connect(lambda checked=False, t=trigger, a=action: self.example_selected.emit(t, a))
            examples.addWidget(use)
            self.example_buttons.append(use)
        mistakes = self.section(body, 'mistakes', '04 · Типичные ошибки')
        mistakes.addWidget(text('• Расплывчатый сигнал: уточните, как вы заметите нужный момент.\n\n• Сложное действие: оставьте один небольшой первый шаг.\n\n• Нереалистичные обещания: учитывайте доступное время и силы.\n\n• Слишком много планов сразу: начните с одного и проверьте его в жизни.\n\n• Игнорирование усталости: план должен помогать заботиться о себе, а не отменять отдых.'))
        mistakes.addWidget(text('В примерах про усталость и ленту можно уточнить действие: например, пройтись две минуты или открыть конкретную задачу.', 'subtitle'))
        source = self.section(body, 'research', 'Научная основа')
        source.addWidget(text('Метод исследован в психологии саморегуляции. Эффект зависит от цели, ситуации и качества плана; это не универсальное средство от прокрастинации.\n\nGollwitzer (1999), Implementation Intentions: Strong Effects of Simple Plans. DOI: 10.1037/0003-066X.54.7.493\n\nGollwitzer & Sheeran (2006), Implementation Intentions and Goal Achievement: A Meta-analysis of Effects and Processes. DOI: 10.1016/S0065-2601(06)38002-1', 'subtitle'))
        layout.addWidget(self.contents)
        self.toggle.toggled.connect(self.set_expanded)
        self.update_visibility()

    def section(self, parent, key, title, default=False):
        toggle = QPushButton()
        toggle.setCheckable(True)
        opened = self.settings.get('sections', {}).get(key, default)
        toggle.setChecked(opened)
        panel = QWidget()
        content = QVBoxLayout(panel)
        content.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        content.setContentsMargins(6, 8, 6, 12)
        content.setSpacing(12)
        panel.setVisible(opened)
        toggle.setText(('▾ ' if opened else '▸ ') + title)
        parent.addWidget(toggle)
        parent.addWidget(panel)

        def changed(checked):
            panel.setVisible(checked)
            toggle.setText(('▾ ' if checked else '▸ ') + title)
            self.settings.setdefault('sections', {})[key] = checked
            self.state_changed.emit()

        toggle.toggled.connect(changed)
        self.sections[key] = (toggle, panel)
        return content

    def update_visibility(self):
        expanded = self.toggle.isChecked()
        self.contents.setVisible(expanded)
        self.toggle.setText('Скрыть гайд' if expanded else 'Показать гайд')

    def set_expanded(self, expanded):
        self.settings['visible'] = expanded
        self.update_visibility()
        self.state_changed.emit()
