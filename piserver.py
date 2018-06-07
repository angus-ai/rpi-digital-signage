# -*- coding: utf-8 -*-

# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import time
import StringIO
import datetime
import pytz
import threading
import Queue
import socket
import struct

import imutils
import numpy as np
import cv2

from picamera import PiCamera
from picamera.array import PiRGBArray

import angus.client

def capture(wres, hres, fps, rot):
    camera = PiCamera()
    camera.rotation = rot
    camera.resolution = (wres, hres)
    camera.framerate = fps
    time.sleep(1.5)

    stream = StringIO.StringIO()

    for _ in camera.capture_continuous(stream,
                                       format="jpeg",
                                       use_video_port=True):
        frame = StringIO.StringIO(stream.getvalue())
        yield frame
        stream.truncate(0)
        stream.seek(0)

class MotionDetector(object):
    T2 = 50*50      # size of minimum image difference

    def __init__(self, howmany_frames=100, threshold=100):
        self.threshold = threshold
        self.last_image = None
        self.howmany = howmany_frames
        self.remains = 0

    def move(self, frame):
        frame = np.asarray(bytearray(frame.getvalue()), dtype="uint8")

        gray = cv2.imdecode(frame, 0)

        if self.last_image is None:
            has_moved = False
        else:
            diff_img = cv2.absdiff(gray, self.last_image)
            _, view = cv2.threshold(diff_img, self.threshold, 255, cv2.THRESH_BINARY)

            has_moved = np.sum(view)/255 > self.T2
        self.last_image = gray
        return has_moved

    def update(self, frame):
        if self.remains > 0:
            self.remains -= 1
            return True
        elif self.move(frame):
            self.remains = self.howmany
            return True

        return False


class FrameServer(threading.Thread):
    def __init__(self):
        super(FrameServer, self).__init__()
        self.inputs = None
        self.daemon = True
        self.socket = None

    def send(self, frame):
        if self.inputs is not None:
            self.inputs.put(frame)

    def loop(self):
        connection = self.socket.accept()[0].makefile('wb')
        print "New incoming connection"
        while True:
            frame = self.inputs.get()
            if frame is None:
                break
            connection.write(struct.pack('<L', len(frame.getvalue())))
            connection.flush()
            connection.write(frame.getvalue())

        connection.write(struct.pack('<L', 0))


    def run(self):
        self.socket = socket.socket()
        self.socket.bind(('0.0.0.0', 8181))
        self.socket.listen(0)

        while True:
            print "Ready for new incoming message"
            self.inputs = Queue.Queue()
            try:
                self.loop()
            except IOError as exc:
                print exc
            self.inputs = None


def main():
    connection = angus.client.connect()

    service = connection.services.get_service("scene_analysis")

    service.enable_session()

    server = FrameServer()
    server.start()


    motion_filter = MotionDetector(20)

    for frame in capture(640, 480, 7, 90):
        server.send(frame)

        if motion_filter.update(frame):
            timestamp = datetime.datetime.now(pytz.utc)

            j = service.process({
                "image": frame,
                "timestamp": timestamp.isoformat(),
                "store": True
            })
            print j.result["entities"]
        else:
            print "Wait movement"


if __name__ == "__main__":
    main()
