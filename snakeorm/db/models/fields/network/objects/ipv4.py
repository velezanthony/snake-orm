import ipaddress
from snakeorm.db.models.fields.network.objects.network import Network

class Ipv4(Network):
    def __init__(self, ip: str, mask: str = None):
        """
        Initializes an instance of the Ipv4 class with an IP address and an optional subnet mask.

        :param ip: IP address in IPv4 format (e.g., '192.168.1.10')
        :param mask: Subnet mask, can be in CIDR notation (e.g., '/24'), long format (e.g., '255.255.255.0'), or None
        """
        # Validate the IP
        self.ip = self.validate_ip(ip)
        self.mask = self.validate_mask(mask)

    def validate_ip(self, ip: str) -> str:
        """
        Validates that the IP address is in the correct format.

        :param ip: IP address to validate
        :return: The validated IP address
        """
        try:
            # Use the ipaddress library to validate the IPv4 address
            ipaddress.IPv4Address(ip)
            return ip
        except ValueError:
            raise ValueError(f"The IP address {ip} is not valid.")

    def validate_mask(self, mask: str) -> str:
        """
        Validates that the subnet mask is in the correct format (either CIDR or long format).

        :param mask: Subnet mask to validate
        :return: The validated subnet mask or None if no mask is provided
        """
        if mask is None:
            return None

        try:
            # If the mask is in CIDR format (e.g., '/24'), validate it
            if mask.startswith('/'):
                network = ipaddress.IPv4Network(f'0.0.0.0{mask}', strict=False)
                return str(network.prefixlen)  # Returns the prefix length of the CIDR mask

            # If the mask is in long format (e.g., '255.255.255.0'), validate it
            ipaddress.IPv4Network(f'0.0.0.0/{mask}', strict=False)
            return mask  # Returns the mask as-is if it's valid

        except ValueError:
            raise ValueError(f"The subnet mask {mask} is not valid.")

    def get_ip_mask(self) -> str:
        """
        Returns the IP address with the subnet mask in CIDR format if mask exists, otherwise just the IP address.

        :return: IP address with subnet mask in CIDR format (e.g., '192.168.1.10/24') or just the IP address (e.g., '192.168.1.10')
        """
        result:str = f"{self.ip}"
        if self.mask != None:
            result += f"/{self.mask}"
            
        return result

    def get_network(self) -> str:
        """
        Returns the network address that the IP belongs to, based on the provided subnet mask.

        :return: Network address in CIDR format
        """
        if not self.mask:
            raise ValueError("Network address cannot be determined without a subnet mask.")
        network = ipaddress.IPv4Network(f"{self.ip}/{self.mask}", strict=False)
        return str(network.network_address)

    def get_broadcast(self) -> str:
        """
        Returns the broadcast address for the network associated with the IP and subnet mask.

        :return: Broadcast address in IPv4 format
        """
        if not self.mask:
            raise ValueError("Broadcast address cannot be determined without a subnet mask.")
        network = ipaddress.IPv4Network(f"{self.ip}/{self.mask}", strict=False)
        return str(network.broadcast_address)

    def is_private(self) -> bool:
        """
        Checks if the IP address is private according to IPv4 private address rules.

        :return: True if the IP address is private, False if it's public
        """
        ip = ipaddress.IPv4Address(self.ip)
        return ip.is_private

# Example usage
if __name__ == "__main__":
    try:
        # Create an instance of the Ipv4 class with an IP and subnet mask
        ipv4 = Ipv4("192.168.1.10", "/24")
        print(f"IP Address with Mask: {ipv4.get_ip_mask()}")
        print(f"Network: {ipv4.get_network()}")
        print(f"Broadcast: {ipv4.get_broadcast()}")
        print(f"Is Private: {ipv4.is_private()}")

        # Trying with a long-format subnet mask
        ipv4_2 = Ipv4("192.168.1.10", "255.255.255.0")
        print(f"IP Address with Long Mask: {ipv4_2.get_ip_mask()}")

        # Trying with no subnet mask
        ipv4_3 = Ipv4("192.168.1.10")
        print(f"IP Address without Mask: {ipv4_3.get_ip_mask()}")
        
    except ValueError as e:
        print(e)
