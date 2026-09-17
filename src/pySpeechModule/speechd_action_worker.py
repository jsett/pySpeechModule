import logging
import threading
import queue

class ActionWorker(threading.Thread):
    """
    Worker for running speak commands on the server
    
    :meta private:
    """
    def __init__(self, server):
        super().__init__()
        self.queue = queue.Queue()
        self.server = server
        self.daemon = True

    def begin(self):
        self.server._begin()

    def end(self):
        self.server._end()

    def speak(self,val):
        self.server._send_audio(val)
    
    def stop(self):
        """Sends the sentinel value to trigger a graceful shutdown."""
        self.queue.put(None)

    def run(self):
        while True:
            item = self.queue.get()
            logging.debug(f"action worker: got item {item}")
            if item is None:
                break
            if (item['command'] == 'begin'):
                self.begin()
            if (item['command'] == 'end'):
                self.end()
            if (item['command'] == 'speak'):
                self.speak(item['val'])