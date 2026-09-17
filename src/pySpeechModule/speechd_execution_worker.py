import logging
import threading
import queue

class ExecutionWorker(threading.Thread):
    """
    Worker for running the execution callbacks.
    
    :meta private:
    """
    def __init__(self):
        super().__init__()
        self.queue = queue.Queue()
        self.daemon = True

    def set_callback(self,callback):
        self._callback = callback

    def stop(self):
        """Sends the sentinel value to trigger a graceful shutdown."""
        self.queue.put(None)

    def run(self):
        while True:
            item = self.queue.get()
            logging.debug(f"execution worker: got item {item}")
            if item is None:
                break
            elif (item['command'] == 'speak'):
                self._callback._speak(item['args'])
            elif (item['command'] == 'settings'):
                self._callback._settings(item['args'])
            elif (item['command'] == 'configure'):
                self._callback.configure(item['args'])