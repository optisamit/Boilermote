from django.test import TestCase

from .models import TemperatureReading


class TemperatureReadingTests(TestCase):
    def test_real_temperature_halves_stored_value(self):
        reading = TemperatureReading(temperature=25)
        self.assertEqual(reading.real_temperature(), 12.5)

    def test_real_temperature_negative(self):
        reading = TemperatureReading(temperature=-11)
        self.assertEqual(reading.real_temperature(), -5.5)

    def test_saved_reading_sets_timestamp_and_str(self):
        reading = TemperatureReading.objects.create(temperature=25)
        fetched = TemperatureReading.objects.get(pk=reading.pk)
        self.assertIsNotNone(fetched.timestamp)
        self.assertEqual(fetched.real_temperature(), 12.5)
        self.assertIn("12.5", str(fetched))
