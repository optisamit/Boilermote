from gpiozero import SPIDevice

class ThermocoupleError(IOError):
    """
    Exception raised when a thermocouple is not connected to the board.
    """
    pass


class Max6675(SPIDevice):
    """
    Extends :class:`SPIDevice` to interface with a MAX6675
    cold-junction-compensated K-Type thermocouple to digital converter.

    This device digitizes the signal from a type-K thermocouple and outputs
    the data in a 12-bit resolution, SPI-compatible format.

    :param spi_args:
        Keyword arguments passed to the :class:`SPIDevice` constructor to
        configure the underlying SPI interface (e.g., `port`, `device`, `rate`).
    """
    def __init__(self, **spi_args):
        """
        Initializes the MAX6675 device and configures the SPI bus.
        """
        super().__init__(**spi_args)
        # The MAX6675 timing diagram shows the clock idling low (CPOL=0) and
        # data being stable for the rising clock edge (CPHA=0). This
        # corresponds to SPI mode 0. The datasheet text states data is read
        # on the falling edge, but common implementations and
        # visual analysis of the timing diagram favor mode 0.
        self._spi.clock_mode = 0

    @property
    def raw_value(self):
        """
        Reads and returns the raw 16-bit integer value from the SPI bus.

        A complete read requires 16 clock cycles. The data is
        read as two 8-bit words and combined into a single 16-bit integer.
        """
        self._check_open()
        raw_bytes = self._spi.read(2)
        return self._words_to_int(raw_bytes)

    @property
    def temperature(self):
        """
        Returns the measured temperature in degrees Celsius (°C).

        The device resolves temperatures to 0.25°C. If the
        thermocouple is not connected, this property will raise a
        :exc:`ThermocoupleError`.
        """
        value = self.raw_value
        # Bit D2 is an open-circuit detector. It goes high if the thermocouple
        # input is open. This corresponds to bit value 4 (0b100).
        if value & 4:
            raise ThermocoupleError("Thermocouple is not connected")

        # The temperature data is contained in bits D14 through D3.
        # We shift the 16-bit value right by 3 to discard the status bits
        # (D0, D1, D2) and isolate the 12-bit temperature reading.
        temp_data = value >> 3

        # Each bit (LSB) of the temperature data corresponds to 0.25°C.
        celsius = temp_data * 0.25
        return celsius

    @property
    def is_connected(self):
        """
        Returns ``True`` if the thermocouple is connected and ``False`` otherwise.

        This state is determined by checking bit D2 of the raw data stream,
        which serves as an open-thermocouple detector. For this feature
        to work, the T- pin must be grounded.
        """
        # A value of 0 in bit 2 (mask 0x04) indicates a connection.
        return (self.raw_value & 4) == 0
