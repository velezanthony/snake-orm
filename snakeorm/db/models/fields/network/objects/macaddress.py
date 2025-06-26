import re

class MacAddress:
    def __init__(self, mac: str):
        """
        Initializes an instance of the MacAddress class with a MAC address.

        :param mac: MAC address in standard format (e.g., '00:14:22:01:23:45')
        """
        self.mac = self.validate_mac(mac)

    def validate_mac(self, mac: str) -> str:
        """
        Validates that the MAC address is in a valid format.

        :param mac: MAC address to validate
        :return: Validated MAC address in string format
        :raises ValueError: If the MAC address is not valid
        """
        mac_regex = r'^([0-9a-fA-F]{2}[:]){5}[0-9a-fA-F]{2}$'
        if re.match(mac_regex, mac):
            return mac.lower()  # Convert MAC to lowercase for consistency
        else:
            raise ValueError(f"The MAC address {mac} is not valid.")

    def get_mac(self) -> str:
        """
        Returns the MAC address in the original format.

        :return: MAC address as a string
        """
        return self.mac

    def get_mac_upper(self) -> str:
        """
        Returns the MAC address in uppercase format.

        :return: MAC address in uppercase
        """
        return self.mac.upper()

    def get_mac_lower(self) -> str:
        """
        Returns the MAC address in lowercase format.

        :return: MAC address in lowercase
        """
        return self.mac

    def get_components(self) -> list:
        """
        Splits the MAC address into its components.

        :return: List of components (e.g., ['00', '14', '22', '01', '23', '45'])
        """
        return self.mac.split(':')

    def is_unicast(self) -> bool:
        """
        Checks if the MAC address is a unicast address.

        :return: True if the MAC address is unicast, False otherwise
        """
        first_byte = int(self.mac.split(':')[0], 16)
        return (first_byte % 2 == 0)  # Unicast MAC addresses have an even first byte

    def is_multicast(self) -> bool:
        """
        Checks if the MAC address is a multicast address.

        :return: True if the MAC address is multicast, False otherwise
        """
        first_byte = int(self.mac.split(':')[0], 16)
        return (first_byte % 2 != 0)  # Multicast MAC addresses have an odd first byte

    def is_broadcast(self) -> bool:
        """
        Checks if the MAC address is a broadcast address.

        :return: True if the MAC address is broadcast, False otherwise
        """
        return self.mac == 'ff:ff:ff:ff:ff:ff'

# Example usage
if __name__ == "__main__":
    try:
        # Create an instance of the MacAddress class
        mac = MacAddress("00:14:22:01:23:45")
        print(f"MAC Address: {mac.get_mac()}")
        print(f"MAC Address (Uppercase): {mac.get_mac_upper()}")
        print(f"MAC Address (Lowercase): {mac.get_mac_lower()}")
        print(f"MAC Address Components: {mac.get_components()}")
        print(f"Is Unicast: {mac.is_unicast()}")
        print(f"Is Multicast: {mac.is_multicast()}")
        print(f"Is Broadcast: {mac.is_broadcast()}")

    except ValueError as e:
        print(e)
