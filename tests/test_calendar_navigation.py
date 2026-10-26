import copy
import tempfile
import unittest
from pathlib import Path

from PySide6.QtCore import QDate, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QTableView
from PySide6.QtTest import QTest
from main import Store, Window


class CalendarNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.window = Window(Store(Path(self.tmp.name) / 'data.json'))
        self.window.resize(850, 650)
        self.window.navigate(3)
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.tmp.cleanup()

    def wheel(self, widget, delta=-120, pixels=None):
        point = widget.rect().center()
        global_pos = widget.mapToGlobal(point)
        event = QWheelEvent(QPointF(point), QPointF(global_pos), pixels or QPoint(),
                            QPoint(0, delta), Qt.MouseButton.NoButton,
                            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.ScrollUpdate, False)
        self.app.sendEvent(widget, event)
        self.app.processEvents()

    def test_year_is_a_real_dropdown_and_selects_leap_year(self):
        page = self.window.wellbeing
        nav = page.calendar_navigation
        nav.year.showPopup()
        self.app.processEvents()
        self.assertTrue(nav.year.view().isVisible())
        index = nav.year.findData(2000)
        view = nav.year.view()
        model_index = nav.year.model().index(index, 0)
        view.scrollTo(model_index)
        self.app.processEvents()
        QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(model_index).center())
        self.assertEqual(page.calendar.yearShown(), 2000)
        nav.month.setCurrentIndex(1)
        page.calendar.setSelectedDate(QDate(2000, 2, 29))
        self.assertEqual(page.selected.isoformat(), '2000-02-29')
        self.assertEqual(nav.year.currentData(), 2000)
        self.assertEqual(nav.month.currentData(), 2)

    def test_page_wheel_over_focused_controls_does_not_edit(self):
        page = self.window.wellbeing
        scroll = self.window.stack.widget(3)
        bar = scroll.verticalScrollBar()
        table = page.calendar.findChild(QTableView)
        targets = [page.sliders[0], page.sliders[1], page.calendar, table.viewport(), page.calendar_navigation.year, page.calendar_navigation.month]
        before = copy.deepcopy(self.window.store.data)
        old_month = (page.calendar.yearShown(), page.calendar.monthShown())
        old_date = page.calendar.selectedDate()
        for target in targets:
            with self.subTest(target=target):
                target.setFocus()
                bar.setValue(0)
                self.wheel(target)
                self.assertGreater(bar.value(), 0)
                self.assertEqual([s.value() for s in page.sliders], [5, 5])
                self.assertEqual((page.calendar.yearShown(), page.calendar.monthShown()), old_month)
                self.assertEqual(page.calendar.selectedDate(), old_date)
        self.assertEqual(self.window.store.data, before)
        self.assertFalse(page.dirty)
        bar.setValue(200)
        self.wheel(page.sliders[0], delta=120)
        self.assertLess(bar.value(), 200)
        bar.setValue(0)
        self.wheel(table.viewport(), delta=0, pixels=QPoint(0, -40))
        self.assertGreater(bar.value(), 0)

    def test_click_keyboard_and_navigation_limits_still_work(self):
        page = self.window.wellbeing
        nav = page.calendar_navigation
        slider = page.sliders[0]
        slider.setFocus()
        QTest.keyClick(slider, Qt.Key.Key_Right)
        self.assertEqual(slider.value(), 6)
        nav.year.setCurrentIndex(nav.year.findData(1))
        nav.month.setCurrentIndex(0)
        self.assertFalse(nav.previous.isEnabled())
        nav.next.click()
        self.assertEqual(page.calendar.monthShown(), 2)
        page.calendar.setCurrentPage(QDate.currentDate().year(), QDate.currentDate().month())
        self.assertFalse(nav.next.isEnabled())
        self.assertEqual(nav.year.currentData(), QDate.currentDate().year())
        for i in range(QDate.currentDate().month(), 12):
            self.assertFalse(nav.month.model().item(i).isEnabled())

    def test_wheel_over_other_form_fields_scrolls_settings(self):
        self.window.navigate(4)
        scroll = self.window.stack.widget(4)
        settings = self.window.sound_settings
        original = settings.tone.currentIndex()
        for target in (settings.tone, settings.volume):
            scroll.verticalScrollBar().setValue(0)
            self.wheel(target)
            self.assertGreater(scroll.verticalScrollBar().value(), 0)
        self.assertEqual(settings.tone.currentIndex(), original)
        self.assertEqual(settings.volume.value(), 35)

    def test_open_dropdown_scroll_does_not_scroll_page(self):
        page = self.window.wellbeing
        scroll = self.window.stack.widget(3)
        combo = page.calendar_navigation.year
        combo.showPopup()
        self.app.processEvents()
        before = scroll.verticalScrollBar().value()
        self.wheel(combo.view().viewport())
        self.assertEqual(scroll.verticalScrollBar().value(), before)
        combo.hidePopup()
