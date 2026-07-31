import pytest
from monitor import ConversationMonitor

def test_first_message_is_checked():
    m = ConversationMonitor()
    m.add_message("lis", "I'd be happy to help!")
    assert m.issues   # must flag even as the very first message
