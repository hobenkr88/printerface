#!/usr/bin/python
# -*- coding: utf-8 -*-

# FIXME: Serial interface does't disconnect on Ctrl+Q

import wx
import serial
import threading
import queue
import time
import zmq
import json
import re

def split_keep(string, sep):
    """Usage:
    >>> list(split_keep("a.b.c.d", "."))
    ['a.', 'b.', 'c.', 'd']
    """
    start = 0
    while True:
        end = string.find(sep, start) + 1
        if end == 0:
            break
        yield string[start:end]
        start = end
    yield string[start:]

## ----------------------------------------------------------------------
# Create an own event type, so that GUI updates can be delegated
# this is required as on some platforms only the main thread can
# access the GUI without crashing. wxMutexGuiEnter/wxMutexGuiLeave
# could be used too, but an event is more elegant.

SERIALRX = wx.NewEventType()
# bind to serial data receive events
EVT_SERIALRX = wx.PyEventBinder(SERIALRX, 0)


class SerialRxEvent(wx.PyCommandEvent):
    eventType = SERIALRX

    def __init__(self, data):
        wx.PyCommandEvent.__init__(self, self.eventType)
        self.data = data


# I don't this this class is used
class InterfaceConnection():
    def __init__(self, main_frame_event_handler):
        
        return None
    
    def Connect(self):
        return None
    
    def Disconnect(self):
        return None
    
    def Read(self):
        return None
    
    def WriteLine(self, message):
        return None
    
    def ReadWriteLoop(self, stop_flag, write_queue):
        return None
    
    

class SerialInterface():
    def __init__(self, main_frame_event_handler):
        
        self.main_frame_event_handler = main_frame_event_handler
        
        self.baudrate = 250000
        self.parity = 'N'
        self.bytesize = 8
        self.stopbits = 1
        
        self.write_queue = queue.Queue()
        #self.un_acked_writes = 0
        
        self.serial_connection = serial.Serial()
        self.read_thread_alive = threading.Event()
        self.read_thread = threading.Thread(target=self.ReadWriteLoop, args=(self.serial_connection, self.read_thread_alive, self.write_queue))
        
        #FIXME: why am I setting self.read_thread = None here?
        self.read_thread = None
        
        return None
    
    def Connect(self, device_string):
        self.port = str(device_string)
        if not self.serial_connection.is_open:
                self.serial_connection.baudrate = self.baudrate
                self.serial_connection.parity = self.parity
                self.serial_connection.bytesize = self.bytesize
                self.serial_connection.stopbits = self.stopbits
                self.serial_connection.port = self.port
                self.serial_connection.open()
                
                self.read_thread_alive.clear()
                self.read_thread = threading.Thread(target=self.ReadWriteLoop, args=(self.serial_connection, self.read_thread_alive, self.write_queue))
                self.read_thread.start()
        

        return True
    
    def Disconnect(self):
        if self.serial_connection.is_open:
            self.read_thread_alive.set()
            alive = True
            while alive:
                self.read_thread.join()
                alive = self.read_thread.is_alive()
            
            self.serial_connection.close()
        
        while not self.write_queue.empty():
            try:
                self.write_queue.get(False)
            except Empty:
                continue
            self.write_queue.task_done()
        
        return True
    
    def Read(self):
        return None
    
    def WriteLine(self, message):
        if message == '':
            return False
        if message == '\n':
            return False
        if message.startswith(";"):
            return False
        
        message_bytes = message.encode('ascii')
        
        self.write_queue.put(message_bytes)
        return None
    
    def ReadWriteLoop(self, serial_connection, stop_flag, write_queue):
        command_line = ""
        previous_write_acked = True

        while not stop_flag.is_set():
            #print('LOOP')
            #print("Command: "+command_line)
            #print("PreviousAcked: "+str(previous_write_acked))
            
            # Read
            data = serial_connection.read(serial_connection.in_waiting or 0)
            data_decoded = data.decode('ascii', 'replace')
            
            if "\n" in data_decoded:
                messages = list(split_keep(data_decoded, "\n"))
                
                for message in messages:
                    command_line += message
                    
                    if command_line.endswith("\n"):
                        if command_line.startswith("start\n"):
                            # Start the printer reporting temperatures.
                            # FIXME: Look for a better sport to put this
                            command = "M155 S1\n"
                            command_bytes = command.encode('ascii')
                            self.write_queue.put(command_bytes)
                            # END FIXME
                        elif command_line == 'ok\n':
                            previous_write_acked = True
                        else:
                            event = SerialRxEvent(command_line)
                            self.main_frame_event_handler.AddPendingEvent(event)
                        command_line = ""
            
            # Write
            if previous_write_acked == True:
                #print('1')
                if not write_queue.empty():
                    print('2')
                    previous_write_acked = False
                    to_send = write_queue.get()
                    print("Sending: "+str(to_send))
                    serial_connection.write(to_send)
                    write_queue.task_done()
            
            # Is there a better way than using sleep here? Also not sure about the speed.
            time.sleep(0.1)
            
        return None

# ----------------------------------------------------------------------

class ZMQInterface():
    def __init__(self):
        self.port = 5555
        
        self.context = zmq.Context()
        
        self.socket = self.context.socket(zmq.PAIR)
        
        return None
    
    def Connect(self, connection_string):
        print('Connect')
        
        self.socket.connect(connection_string)
        
        reply = self.socket.recv()
        print(reply)
        return None
        
    def Disconnect(self, connection_string):
        print('Disconnect')
        print(dir(self.socket))
        return None
    
    def SendPacket(self, type, data=""):
        
        packet = {
            'type': type,
            'data': data
        }
        packet_bytes = json.dumps(packet).encode()
        self.socket.send(packet_bytes)
        
        return None
    
    def ReadWriteLoop(self):
        while True:
            pass
        
        return None
        
# ----------------------------------------------------------------------

class ManualControlsPanel(wx.Panel):
    def __init__(self, parent, serial_connection):
        self.parent = parent
        self.serial_connection = serial_connection
        
        super().__init__(self.parent)

        self.x_interval = "1"
        self.y_interval = "1"
        self.z_interval = "1"
        self.e_interval = "1"
        self.target_bed_temp = "0"
        self.target_extruder_temp = "0"
        
        self.InitUI()
        self.BindEvents()
        return None
    
    def InitUI(self):
        self.sizer = wx.BoxSizer(wx.VERTICAL)

        self.positional_controls_sizer = wx.GridSizer(6,3, 0, 0)
        self.temperatur_controls_sizer = wx.GridSizer(2,3, 0, 0)
        
        self.x_details = wx.Panel(self)
        self.y_details = wx.Panel(self)
        self.z_details = wx.Panel(self)
        self.e_details = wx.Panel(self)

        self.x_details_sizer = wx.BoxSizer(wx.VERTICAL)
        self.y_details_sizer = wx.BoxSizer(wx.VERTICAL)
        self.z_details_sizer = wx.BoxSizer(wx.VERTICAL)
        self.e_details_sizer = wx.BoxSizer(wx.VERTICAL)
        

        self.x_text = wx.StaticText(self.x_details, label="X Axis: ")
        self.y_text = wx.StaticText(self.y_details, label="Y Axis: ")
        self.z_text = wx.StaticText(self.z_details, label="Z Axis: ")
        self.e_text = wx.StaticText(self.e_details, label="E Axis: ")
        
        self.x_interval_textbox = wx.TextCtrl(self.x_details, value=self.x_interval)
        self.y_interval_textbox = wx.TextCtrl(self.y_details, value=self.y_interval)
        self.z_interval_textbox = wx.TextCtrl(self.z_details, value=self.z_interval)
        self.e_interval_textbox = wx.TextCtrl(self.e_details, value=self.e_interval)
        
        self.x_details_sizer.Add(self.x_text, 0)
        self.x_details_sizer.Add(self.x_interval_textbox, 0)
        self.y_details_sizer.Add(self.y_text, 0)
        self.y_details_sizer.Add(self.y_interval_textbox, 0)
        self.z_details_sizer.Add(self.z_text, 0)
        self.z_details_sizer.Add(self.z_interval_textbox, 0)
        self.e_details_sizer.Add(self.e_text, 0)
        self.e_details_sizer.Add(self.e_interval_textbox, 0)

        self.x_details.SetSizer(self.x_details_sizer)
        self.y_details.SetSizer(self.y_details_sizer)
        self.z_details.SetSizer(self.z_details_sizer)
        self.e_details.SetSizer(self.e_details_sizer)

        # FIXME: I think these buttons should have a different parent (same with other buttons on controls)
        self.x_plus_button = wx.Button(self, label="+")
        self.x_minus_button = wx.Button(self, label="-")
        
        self.y_plus_button = wx.Button(self, label="+")
        self.y_minus_button = wx.Button(self, label="-")
        
        self.z_plus_button = wx.Button(self, label="+")
        self.z_minus_button = wx.Button(self, label="-")
        
        self.e_plus_button = wx.Button(self, label="+")
        self.e_minus_button = wx.Button(self, label="-")
        
        


        self.positional_controls_sizer.AddMany([
            (self.x_details, 0, wx.EXPAND),
            (self.x_minus_button, 0, wx.EXPAND),
            (self.x_plus_button, 0, wx.EXPAND),
            (self.y_details, 0, wx.EXPAND),
            (self.y_minus_button, 0, wx.EXPAND),
            (self.y_plus_button, 0, wx.EXPAND),
            (self.z_details, 0, wx.EXPAND),
            (self.z_minus_button, 0, wx.EXPAND),
            (self.z_plus_button, 0, wx.EXPAND),
            (self.e_details, 0, wx.EXPAND),
            (self.e_minus_button, 0, wx.EXPAND),
            (self.e_plus_button, 0, wx.EXPAND),
            
        ])
        

        # FIXME: This is ugly
        self.target_bed_temp_details = wx.Panel(self)
        self.current_bed_temp_details = wx.Panel(self)

        self.target_extruder_temp_details = wx.Panel(self)
        self.current_extruder_temp_details = wx.Panel(self)


        self.target_bed_temp_sizer = wx.BoxSizer(wx.VERTICAL)
        self.current_bed_temp_sizer = wx.BoxSizer(wx.VERTICAL)
        self.target_extruder_temp_sizer = wx.BoxSizer(wx.VERTICAL)
        self.current_extruder_temp_sizer = wx.BoxSizer(wx.VERTICAL)

        self.target_bed_temp_text = wx.StaticText(self.target_bed_temp_details, label="Target Bed Temp: ")
        self.target_bed_temp_textbox = wx.TextCtrl(self.target_bed_temp_details, value=self.target_bed_temp)

        self.current_bed_temp_text = wx.StaticText(self.current_bed_temp_details, label="Current Bed Temp: ")
        self.current_bed_temp_textbox = wx.StaticText(self.current_bed_temp_details, label=self.target_bed_temp)
        
        self.target_extruder_temp_text = wx.StaticText(self.target_extruder_temp_details, label="Target Extruder Temp: ")
        self.target_extruder_temp_textbox = wx.TextCtrl(self.target_extruder_temp_details, value=self.target_extruder_temp)

        self.current_extruder_temp_text = wx.StaticText(self.current_extruder_temp_details, label="Current Extruder Temp: ")
        self.current_extruder_temp_textbox = wx.StaticText(self.current_extruder_temp_details, label=self.target_extruder_temp)

        self.target_bed_temp_sizer.Add(self.target_bed_temp_text, 0)
        self.target_bed_temp_sizer.Add(self.target_bed_temp_textbox, 0)
        self.current_bed_temp_sizer.Add(self.current_bed_temp_text, 0)
        self.current_bed_temp_sizer.Add(self.current_bed_temp_textbox, 0)

        self.target_extruder_temp_sizer.Add(self.target_extruder_temp_text, 0)
        self.target_extruder_temp_sizer.Add(self.target_extruder_temp_textbox, 0)
        self.current_extruder_temp_sizer.Add(self.current_extruder_temp_text, 0)
        self.current_extruder_temp_sizer.Add(self.current_extruder_temp_textbox, 0)

        self.target_bed_temp_details.SetSizer(self.target_bed_temp_sizer)
        self.current_bed_temp_details.SetSizer(self.current_bed_temp_sizer)
        self.target_extruder_temp_details.SetSizer(self.target_extruder_temp_sizer)
        self.current_extruder_temp_details.SetSizer(self.current_extruder_temp_sizer)

        self.set_target_bed_temp_button = wx.Button(self, label="Set Bed Temp")

        self.set_target_extruder_temp_button = wx.Button(self, label="Set Extruder Temp")

        self.temperatur_controls_sizer.AddMany([
            (self.target_bed_temp_details, 0, wx.EXPAND),
            (self.current_bed_temp_details, 0, wx.EXPAND),
            (self.set_target_bed_temp_button, 0, wx.EXPAND),
            (self.target_extruder_temp_details, 0, wx.EXPAND),
            (self.current_extruder_temp_details, 0, wx.EXPAND),
            (self.set_target_extruder_temp_button, 0, wx.EXPAND),
        ])


        self.sizer.Add(self.positional_controls_sizer, 1, wx.EXPAND)
        self.sizer.Add(self.temperatur_controls_sizer, 1, wx.EXPAND)
        self.sizer.AddStretchSpacer(1)
        
        self.SetSizer(self.sizer)
        
        return None
    
    def BindEvents(self):
        self.Bind(wx.EVT_TEXT, self.OnXIntervalChange, self.x_interval_textbox)
        self.Bind(wx.EVT_TEXT, self.OnYIntervalChange, self.y_interval_textbox)
        self.Bind(wx.EVT_TEXT, self.OnZIntervalChange, self.z_interval_textbox)
        self.Bind(wx.EVT_TEXT, self.OnTargetBedTempChange, self.target_bed_temp_textbox)
        self.Bind(wx.EVT_TEXT, self.OnTargetExtruderTempChange, self.target_extruder_temp_textbox)

        self.Bind(wx.EVT_BUTTON, self.OnXMinus, self.x_minus_button)
        self.Bind(wx.EVT_BUTTON, self.OnXPlus, self.x_plus_button)
        
        self.Bind(wx.EVT_BUTTON, self.OnYMinus, self.y_minus_button)
        self.Bind(wx.EVT_BUTTON, self.OnYPlus, self.y_plus_button)
        
        self.Bind(wx.EVT_BUTTON, self.OnZMinus, self.z_minus_button)
        self.Bind(wx.EVT_BUTTON, self.OnZPlus, self.z_plus_button)
        
        self.Bind(wx.EVT_BUTTON, self.OnEMinus, self.e_minus_button)
        self.Bind(wx.EVT_BUTTON, self.OnEPlus, self.e_plus_button)

        self.Bind(wx.EVT_BUTTON, self.OnSetTargetBedTemp, self.set_target_bed_temp_button)

        self.Bind(wx.EVT_BUTTON, self.OnSetTargetExtruderTemp, self.set_target_extruder_temp_button)

        return None

    # FIXME: Might also want to check if I can get text from event instad
    def OnXIntervalChange(self, e):
        new_interval = self.x_interval_textbox.GetLineText(0)
        self.z_interval = new_interval
        return None
    
    def OnYIntervalChange(self, e):
        new_interval = self.y_interval_textbox.GetLineText(0)
        self.z_interval = new_interval
        return None
    
    def OnZIntervalChange(self, e):
        new_interval = self.z_interval_textbox.GetLineText(0)
        self.z_interval = new_interval
        return None

    def OnTargetBedTempChange(self, e):
        new_target_bed_temp = self.target_bed_temp_textbox.GetLineText(0)
        self.target_bed_temp = new_target_bed_temp
        return None
    
    def OnTargetExtruderTempChange(self, e):
        new_target_extruder_temp = self.target_extruder_temp_textbox.GetLineText(0)
        self.target_extruder_temp = new_target_extruder_temp
        return None
    
    def OnXMinus(self, e):
        command = "G91\nG0 X-"+self.z_interval+" F1000\nG90\n"
        self.serial_connection.WriteLine(command)
        return None
    
    def OnXPlus(self, e):
        command = "G91\nG0 X+"+self.z_interval+" F1000\nG90\n"
        self.serial_connection.WriteLine(command)
        return None
        
    def OnYMinus(self, e):
        command = "G91\nG0 Y-"+self.z_interval+" F1000\nG90\n"
        self.serial_connection.WriteLine(command)
        return None
    
    def OnYPlus(self, e):
        command = "G91\nG0 Y+"+self.z_interval+" F1000\nG90\n"
        self.serial_connection.WriteLine(command)
        return None
    
    def OnZMinus(self, e):
        command = "G91\nG0 Z-"+self.z_interval+" F1000\nG90\n"
        self.serial_connection.WriteLine(command)
        return None
    
    def OnZPlus(self, e):
        command = "G91\nG0 Z+"+self.z_interval+" F1000\nG90\n"
        self.serial_connection.WriteLine(command)
        return None
    
    def OnEMinus(self, e):
        
        return None
    
    def OnEPlus(self, e):
        
        return None
    
    def OnSetTargetBedTemp(self, e):
        #command = "M149 F\nM140 S"+self.target_bed_temp+"\nM149 C\n"   # This is the command to change to farenheight
        command = "M140 S"+self.target_bed_temp+"\n"
        self.serial_connection.WriteLine(command)
        return None
    
    def OnSetTargetExtruderTemp(self, e):
        command = "M104 S"+self.target_extruder_temp+"\n"
        self.serial_connection.WriteLine(command)
        return None
    
    def OnCurrentTempsUpdated(self, e):
        if e.data.startswith(" T:"):
            current_bed_temp = re.search('(?<=B:)(\d\d\\.\d\d)', e.data)
            self.current_bed_temp_textbox.SetLabel(current_bed_temp.group(0))
            current_extruder_temp = re.search('(?<=T:)(\\d\\d\\.\\d\\d)', e.data)
            self.current_extruder_temp_textbox.SetLabel(current_extruder_temp.group(0))
        return None
    
# ----------------------------------------------------------------------
    
class ScriptingPanel(wx.Panel):
    def __init__(self, parent, main_frame, serial_interface):
        self.parent = parent
        self.main_frame = main_frame
        self.serial_interface = serial_interface
        
        super().__init__(self.parent)
        
        self.running_script = ""
        
        self.InitUI()
        self.BindEvents()
        return None
        
    def InitUI(self):
        self.sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.script_content_textbox = wx.TextCtrl(self, style=wx.TE_MULTILINE)
        
        self.script_controls = wx.Panel(self)
        self.script_controls_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.load_button = wx.Button(self.script_controls, label="Load")
        self.run_button = wx.Button(self.script_controls, label="Run")
        self.script_controls_sizer.Add(self.load_button, 1, wx.EXPAND)
        self.script_controls_sizer.Add(self.run_button, 1, wx.EXPAND)
        self.script_controls.SetSizer(self.script_controls_sizer)
        
        self.sizer.Add(self.script_controls, 0, wx.EXPAND)
        self.sizer.Add(self.script_content_textbox, 1, wx.EXPAND)
        
        self.SetSizer(self.sizer)
        
        return None
    
    def BindEvents(self):
        self.Bind(wx.EVT_TEXT, self.OnScriptContentChanged, self.script_content_textbox)
        
        self.Bind(wx.EVT_BUTTON, self.OnLoadScript, self.load_button)
        self.Bind(wx.EVT_BUTTON, self.OnRunScript, self.run_button)
        
        return None
        
    def OnScriptContentChanged(self, e):
        #self.script_content = e.GetString()
        return None
    
    def OnLoadScript(self, e):
        print('Load script')
        with wx.FileDialog(self, "Open XYZ file", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as file_dialog:
            if file_dialog.ShowModal() == wx.ID_CANCEL:
                return
            
            pathname = file_dialog.GetPath()
            try:
                with open(pathname, 'r') as file:
                    script_content = file.read()
                    self.script_content_textbox.SetValue(script_content)
            except IOError:
                print("Cannot open file", pathname)
        return None
    
    def OnRunScript(self, e):
        print('Run script')
        script_content = self.script_content_textbox.GetValue() + "\n"
        self.running_script = script_content
        
        running_script_lines_array = self.running_script.split("\n")
        for line in running_script_lines_array:
            #print(self.main_frame.printer_message_overflow)
            #while self.main_frame.printer_message_overflow != 0:
            #    pass
            #print(repr(line))
            to_send = line + "\n"
            self.main_frame.OnSerialWrite(to_send)
            self.serial_interface.WriteLine(to_send)
        #self.serial_connection.write(bytes(script_content, 'ascii'))
        
        return None

# ----------------------------------------------------------------------

class MessageLogPanel(wx.Panel):
    def __init__(self, parent):
        self.parent = parent
        
        super().__init__(self.parent)
        
        self.message_buffer = ""
        
        self.InitUI()
        
        return None
        
    def InitUI(self):
        self.log_panel = wx.TextCtrl(self, style=(wx.TE_MULTILINE | wx.TE_READONLY))
        
        self.main_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.main_sizer.Add(self.log_panel, 1, wx.EXPAND)
        
        self.SetSizer(self.main_sizer)
        
        return None
    
    def Append(self, message):
        self.message_buffer += str(message)
        self.log_panel.SetValue(self.message_buffer)
        self.log_panel.SetInsertionPoint(-1)
        
        self.Update()
        
        return None

# ----------------------------------------------------------------------

class Printerface(wx.Frame):

    def __init__(self, *args, **kwargs):
        super(Printerface, self).__init__(*args, **kwargs)
        
        #self.printer_message_overflow = 0
        
        self.settings = {
            
        }
        self.state = {
            'interface_type': "USB",
            'interface_connected': False
        }
        
        self.serial_interface = SerialInterface(self.GetEventHandler())
        self.zmq_interface = ZMQInterface()
        
        #self.serial_interface_connected = False
        self.thread = None
        self.alive = threading.Event()
        
        self.InitUI()
        
        return None

    def InitUI(self):
        self.InitMenubar()
        self.InitMainPanel()
        self.BindEvents()

        self.SetSize((1000, 600))
        self.SetTitle('Simple menu')
        self.Centre()
        
        return None
    
    def InitMenubar(self):
        self.menubar = wx.MenuBar()
        self.fileMenu = wx.Menu()
        self.fileItem = self.fileMenu.Append(wx.ID_EXIT, 'Quit', 'Quit application')
        self.menubar.Append(self.fileMenu, '&File')
        self.SetMenuBar(self.menubar)
        return None
    
    def InitMainPanel(self):
        self.main_panel = wx.Panel(self)
        
        self.main_content_panel = wx.Panel(self.main_panel)
        self.message_log_panel = MessageLogPanel(self.main_panel)
        
        self.connection_panel = wx.Panel(self.main_content_panel)
        
        self.interface_type = wx.Choice(self.connection_panel, choices=['USB', 'ZMQ'])
        self.interface_type.SetSelection(0)
        
        self.connection_string_textbox = wx.TextCtrl(self.connection_panel, value="/dev/ttyUSB0")
        self.connect_button = wx.Button(self.connection_panel, label="Connect")
        
        self.notebook = wx.Notebook(self.main_content_panel)
        self.manual_control_panel = ManualControlsPanel(self.notebook, self.serial_interface)
        self.scripting_panel = ScriptingPanel(self.notebook, self, self.serial_interface)
        
        self.notebook.AddPage(self.manual_control_panel, "Controls")
        self.notebook.AddPage(self.scripting_panel, "Scripting")
        
        
        self.connection_panel_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.main_panel_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.main_content_sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.connection_panel_sizer.Add(self.interface_type, 0, wx.EXPAND)
        self.connection_panel_sizer.Add(self.connection_string_textbox, 1, wx.EXPAND)
        self.connection_panel_sizer.Add(self.connect_button, 0, wx.EXPAND)
        self.connection_panel.SetSizer(self.connection_panel_sizer)
        
        self.main_content_sizer.Add(self.connection_panel, 0, wx.EXPAND)
        self.main_content_sizer.Add(self.notebook, 1, wx.EXPAND)
        self.main_content_panel.SetSizer(self.main_content_sizer)
        
        self.main_panel_sizer.Add(self.main_content_panel, 1, wx.EXPAND)
        self.main_panel_sizer.Add(self.message_log_panel, 1, wx.EXPAND)
        
        self.main_panel.SetSizer(self.main_panel_sizer)
        return None
    
    def BindEvents(self):
        # Menu events
        self.Bind(wx.EVT_MENU, self.OnQuit, self.fileItem)
        
        # Button events
        self.Bind(wx.EVT_BUTTON, self.OnConnectButton, self.connect_button)
        
        
        # Other interaction events
        self.Bind(wx.EVT_CHOICE, self.OnChooseConnectionType, self.interface_type)
        
        # Misc events
        self.Bind(EVT_SERIALRX, self.OnSerialRead)
        
        return None

    def OnQuit(self, e):
        self.Close()
        
        return None
    
    def OnChooseConnectionType(self, e):
        interface_type = e.GetString()
        self.state['interface_type'] = interface_type
        
        if interface_type == 'USB':
            self.connection_string_textbox.SetValue('/dev/ttyUSB0')
        if interface_type == 'ZMQ':
            self.connection_string_textbox.SetValue('tcp://192.168.1.59:5555')
        return None
    
    def OnConnectButton(self, e):
        # Disconnect
        if self.state['interface_connected']:
            if self.state['interface_type'] == 'USB':
                self.DisconnectSerial()
            if self.state['interface_type'] == 'ZMQ':
                self.DisconnectZMQ()
            self.state['interface_connected'] = None
            self.connect_button.SetLabel('Connect')
        
        # Connect
        else:
            if self.state['interface_type'] == 'USB':
                serial_interface = self.ConnectSerial()
                self.state['interface_connected'] = serial_interface
            if self.state['interface_type'] == 'ZMQ':
                zmq_interface = self.ConnectZMQ()
                self.state['interface_connected'] = zmq_interface
            self.connect_button.SetLabel('Disconnect')

        return None
        
    def ConnectSerial(self):
        connection_string = self.connection_string_textbox.GetValue()
        if self.serial_interface.Connect(connection_string):
            return self.serial_interface
        else:
            return None
    
    def DisconnectSerial(self):
        self.serial_interface.Disconnect()
        return None
    
    def ConnectZMQ(self):
        connection_string = self.connection_string_textbox.GetValue()
        if self.zmq_interface.Connect(connection_string):
            return self.zmq_interface
        else:
            return None
        
    def DisconnectZMQ(self):
        return None
    
    def OnSerialRead(self, e):
        message = e.data

        self.message_log_panel.Append(message)
        self.manual_control_panel.OnCurrentTempsUpdated(e)
        return None
    
    def OnSerialWrite(self, message):
        #self.printer_message_overflow += 1
        return None


def main():

    app = wx.App()
    pf = Printerface(None)
    pf.Show()
    app.MainLoop()


if __name__ == '__main__':
    main()
