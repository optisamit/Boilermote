from django.db import models

class TemperatureReading(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True)
    temperature = models.IntegerField(db_comment='Temperature, in celsius. Doubled in order to keep the field integer')

    def real_temperature(self):
        return self.temperature / 2

    def __str__(self):
        return f'{self.timestamp}: {self.real_temperature()}'
