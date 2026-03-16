import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Project Root
sys.path.append(os.getcwd())

from scripts.ib_watchdog import is_port_open, is_app_running
from App.USTradingController import USTradingController

class TestIBAutomation(unittest.TestCase):
    
    def test_watchdog_port_check(self):
        """Test the port checking logic."""
        # This will depend on the current environment but we can mock socket
        with patch('socket.socket') as mock_socket:
            mock_socket.return_value.__enter__.return_value.connect_ex.return_value = 0
            self.assertTrue(is_port_open('127.0.0.1', 4002))
            
            mock_socket.return_value.__enter__.return_value.connect_ex.return_value = 61 # Connection refused
            self.assertFalse(is_port_open('127.0.0.1', 4002))

    def test_watchdog_app_check(self):
        """Test the app running check."""
        with patch('subprocess.check_output') as mock_output:
            mock_output.return_value = b'12345'
            self.assertTrue(is_app_running('IB Gateway'))
            
            from subprocess import CalledProcessError
            mock_output.side_effect = CalledProcessError(1, 'pgrep')
            self.assertFalse(is_app_running('IB Gateway'))

    def test_controller_error_handler(self):
        """Test if the controller properly handles IB signals."""
        # Create a mock controller (no need to start the loop)
        controller = USTradingController()
        controller.log_message = MagicMock()
        
        # Test error code 1100 (connection lost)
        controller.on_ib_error(reqId=-1, errorCode=1100, errorString="Connection lost", contract=None)
        controller.log_message.emit.assert_any_call("🚨 [IB-网络状态] 1100: Connection lost")
        
        # Test error code 1101 (connection restored)
        controller.on_ib_error(reqId=-1, errorCode=1101, errorString="Connection restored", contract=None)
        controller.log_message.emit.assert_any_call("📡 [IB-网络状态] 1101: Connection restored")

if __name__ == '__main__':
    unittest.main()
