import sys
import logging
import threading
import select
import soundfile as sf
import queue
import time

from .speechd_action_worker import ActionWorker
from .speechd_execution_worker import ExecutionWorker
from .speechd_utilities import hdlc_escape

stdout = sys.stdout
stdin = sys.stdin
sys.stdout = sys.stderr

logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

class SpeechServer():
    """
    This is the server class, it handles running the protocal.

    .. note:: we set ``sys.stdout = sys.stderr``, this is to ensure that users don't accedentally break the protocal. Anything printed to stdout may break the server.
    """
    def __init__(self):
        """
        :meta private:
        """

        self.line_count = 0

        self.execution_worker = ExecutionWorker()
        self.action_worker = ActionWorker(server=self)

        self.voices = []
        self.server_lock = threading.RLock()
        self.stop_lock = threading.RLock()
        self.stop = False # make sure you use stop_lock when using this.
    
    def _readline(self, block=True):
        """
        This is basically pythons readline but with the added ability to do it none blocking.

        :meta private:
        """

        try:
            if (not block):
                timeout = 0.0
                ready, _, _ = select.select([stdin], [], [], timeout)
                if ready:
                    output = stdin.readline()
                    logging.debug(f"line {self.line_count}: {output[:-1]}")
                    self.line_count = self.line_count + 1
                    return output
                return None
            else:
                output = stdin.readline()
                logging.debug(f"line {self.line_count}: {output[:-1]}")
                self.line_count = self.line_count + 1
                return output
        except Exception as e:
            logging.error(f"_readline: {e}")


    def _begin(self):
        """
        Send command telling speechd we are starting to send audio data.

        :meta private:
        """

        with self.server_lock:
            stdout.write("701 BEGIN\n")
            stdout.flush()
    def _end(self):
        """
        Tells speechd we are done sending audio data.

        :meta private:
        """

        with self.server_lock:
            stdout.write("702 END\n")
            stdout.flush()
    def _mark(self, mark):
        """
        Tells speechd which mark we are on.

        :meta private:
        """

        if (mark==""):
            return
        
        with self.server_lock:
            stdout.write(f"700-{mark}\n700 INDEX MARK\n")
            stdout.flush()

    def _send_audio(self, val):
        """
        Send audio data to speechd.

        :meta private:
        """

        with self.server_lock:
            logging.debug("server: _send_audio")
            data = val['audio']
            sample_rate = val['rate']
            mark = val['mark']

            chunk_size = 5000
            for i in range(0, len(data), chunk_size):
                start_time = time.time()
                tmp_data = data[i : i + chunk_size]
                num_samples = len(tmp_data)
                tmp_data = tmp_data.tobytes()
                stdout.write(f"705-bits=16\n")
                stdout.flush()
                stdout.write(f"705-num_channels=1\n")
                stdout.flush()
                stdout.write(f"705-sample_rate={sample_rate}\n")
                stdout.flush()
                stdout.write(f"705-num_samples={num_samples}\n")
                stdout.flush()
                stdout.write(f"705-big_endian=0\n")
                stdout.flush()
                stdout.write(f"705-AUDIO")
                stdout.flush()
                stdout.buffer.write(b'\x00')

                tmp_data2 = hdlc_escape(tmp_data)
                stdout.buffer.write(tmp_data2)
                stdout.write("\n")
                stdout.write("705 AUDIO\n")
                stdout.flush()
                end_time = time.time()
                total_time = end_time-start_time
                self._process(block=False)
            self._mark(mark)

    def _configure(self):
        """
        Get the config file path and send it to the client.

        :meta private:
        """

        if len(sys.argv) > 1:
            configfile = sys.argv[1]
            self.execution_worker.queue.put({"command": "configure", "args": configfile})

    def parse_set_params(self,ack: int, param_type: str):
        """
        Get a settings string.

        :meta private:
        """

        with self.server_lock:
            stdout.write(f"{ack} OK RECEIVING {param_type} SETTINGS\n")
            stdout.flush()

        output = {}

        while (True):
            line = self._readline()
            if (line == ".\n"):
                break
            line_clean = line.rstrip("\n")
            var, val = line_clean.split("=", 1)
            output[var] = val

        return output
    
    def _audio(self):
        """
        :meta private:
        """

        tmp = self.parse_set_params(207, "AUDIO")
        with self.server_lock:
            stdout.write("203 OK AUDIO INITIALIZED\n")
            stdout.flush()

    def _loglevel(self):
        """
        Sets the logging level from a settings string.

        The logging levels don't quit match up with speechd but we try and get them as close as possible.
        see this link for the speechd logging levels.
        https://htmlpreview.github.io/?https://github.com/brailcom/speechd/blob/master/doc/speech-dispatcher.html#Log-Levels

        :meta private:
        """

        levels = {'5': logging.DEBUG, '4': logging.INFO, '3': logging.WARNING, '2': logging.ERROR, '1': logging.CRITICAL}

        tmp = self.parse_set_params(207, "LOGLEVEL")
        logging.critical(f"Changing log level to {tmp['log_level']}")
        if (tmp['log_level'] == '0'):
            logging.disable(logging.CRITICAL) # Disable all logging globally.
        else:
            logging.disable(logging.NOTSET) # Enable all logging globally.
            logging.getLogger().setLevel(levels[tmp['log_level']]) # set the logging level.
        
        with self.server_lock:
            stdout.write("203 OK LOGLEVEL SET\n")
            stdout.flush()
    
    def _list_voices(self):
        """
        List the voices and send them back to speechd.

        :meta private:
        """
        voices = self.voices
        with self.server_lock:
            for voice in voices:
                name = voice['name'] if 'name' in voice else "none"
                language = voice['language'] if 'language' in voice else "none"
                variant = voice['variant'] if 'variant' in voice else "none"
                stdout.write(f"200-{name}\t{language}\t{variant}\n")

            stdout.write("200 OK VOICE LIST SENT\n")
            stdout.flush()

    def _setting(self):
        """
        Receive setting from speechd.

        :meta private:
        """
        tmp = self.parse_set_params(203, "")
        self.execution_worker.queue.put({"command": "settings", "args": tmp})
        with self.server_lock:
            stdout.write("203 OK SETTINGS RECEIVED\n")
            stdout.flush()
    
    # def _speak_test(self):
    #     data, samplerate = sf.read("deep_learning.wav", dtype='int16')
    #     val = {"audio": data, "rate": samplerate, "mark": ""}
    #     self._begin()
    #     self._send_audio(val)
    #     self._end()

    def _speak(self):
        """
        Get a speak command from speechd.

        :meta private:
        """
        with self.server_lock:
            stdout.write("202 OK RECEIVING MESSAGE\n")
            stdout.flush()
        
        full_text = ""

        while (True):
            line = self._readline()
            if (line == ".\n"):
                break
            else:
                full_text = full_text + line[:-1] + " "
            
        self.execution_worker.queue.put({"command": "speak", "args": full_text})

        with self.server_lock:
            stdout.write("200 OK SPEAKING\n")
            stdout.flush()
    
    def stop_get(self):
        """
        Get the value of the stop var.

        :meta private:
        """
        with self.stop_lock:
            return self.stop
    def stop_set(self, val):
        """
        Set the value of the stop var.

        :meta private:
        """
        with self.stop_lock:
            self.stop = val
    def _stop(self):
        """
        Stop the client.

        :meta private:
        """
        self.stop_set(True)
        with self.server_lock:
            stdout.write("703 STOP\n")
            stdout.flush()
    def _pause(self):
        """
        Stop the client.

        :meta private:
        """

        self.stop_set(True)
        with self.server_lock:
            stdout.write("704 PAUSE\n")
            stdout.flush()

    def _process(self, block=True):
        """
        Process commands from speechd.

        :meta private:
        """
        while (True):
            line = self._readline(block)
            if (line == None):
                break
            if (line == ""):
                break
            if (line == "SPEAK\n"):
                self._speak()
            elif (line == "SOUND_ICON\n"):
                self._speak()
            elif (line == "CHAR\n"):
                self._speak()
            elif (line == "KEY\n"):
                self._speak()
            elif (line[:11] == "LIST VOICES"):
                self._list_voices()
            elif (line == "SET\n"):
                self._setting()
            elif (line == "AUDIO\n"):
                self._audio()
            elif (line == "LOGLEVEL\n"):
                self._loglevel()
            elif (line == "STOP\n"):
                self._stop()
            elif (line == "PAUSE\n"):
                self._pause()
            elif (line[:5] == "DEBUG"):
                # TODO: not sure the diffrence between log level and debug
                pass
            elif (line == "QUIT\n"):
                break
            else:
                logging.error("_process: unknown command")
                logging.error(line)

    def start(self, callback):
        """
        Starts the mainloop and sets the client callback.
        """

        self._callback = callback
        # keep a local copy of the voices
        # it should be set at the start and never changed.
        if hasattr(callback, "voices"):
            self.voices = callback.voices
        else:
            self.voices = [{"name": "GenericPythonModule", "language": "en", "variant": "none"}]

        # Start the worker threads.
        self.execution_worker.set_callback(callback)
        self.execution_worker.start()
        self.action_worker.start()
        self._callback._set_init(self.action_worker.queue, self)

        # run configure.
        self._configure()

        line = self._readline()
        if (line != "INIT\n"):
            logging.error("ERROR: Server did not start with INIT\n")

        msg = "GOOD"
        stdout.write(f"299-{msg}\n")
        stdout.write("299 OK LOADED SUCCESSFULLY\n")
        stdout.flush()

        logging.info("server: Starting _process()")
        self._process()

        # let the workers stop before quitting
        self.execution_worker.stop()
        self.action_worker.stop()
        self.execution_worker.join()
        self.action_worker.join()
        logging.debug("server: Quiting")