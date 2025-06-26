from abc import ABC, abstractmethod

class Network(ABC):
    
    @abstractmethod
    def __init__(self, ip: str, mac: str):
        """
        Abstract base class that enforces the structure of its subclasses.
        
        :param ip: IP address as a string (e.g., '192.168.1.1')
        :param mac: MAC address as a string (e.g., '00:14:22:01:23:45')
        """
        # We define the parameters but don't implement the actual constructor
        # Subclasses must implement this constructor
        pass

    @abstractmethod
    def validate_ip(self, ip: str) -> str:
        """
        Validates the provided IP address.
        :param ip: IP address to validate.
        :return: The validated IP address.
        """
        pass

    @abstractmethod
    def validate_mask(self, mask: str) -> str:
        """
        Validates the provided subnet mask.
        :param mask: Subnet mask to validate.
        :return: The validated subnet mask.
        """
        pass

    @abstractmethod
    def get_ip_mask(self) -> str:
        """
        Returns the IP address with the subnet mask in CIDR format.
        :return: IP address with the subnet mask in CIDR format (e.g., '192.168.1.10/24').
        """
        pass

    @abstractmethod
    def get_network(self) -> str:
        """
        Returns the network address associated with the IP and subnet mask.
        :return: Network address in CIDR format (e.g., '192.168.1.0/24').
        """
        pass

    @abstractmethod
    def get_broadcast(self) -> str:
        """
        Returns the broadcast address for the network.
        :return: Broadcast address (e.g., '192.168.1.255').
        """
        pass

    @abstractmethod
    def is_private(self) -> bool:
        """
        Checks whether the provided IP address is private.
        :return: True if the IP is private, False if it's public.
        """
        pass