# This file is part of the Astrometry.net suite.
# Licensed under a 3-clause BSD style license - see LICENSE
from __future__ import print_function

'''
This code allows one to interact with the JPL Horizons ephemeris
service via their telnet interface.  Yes, telnet.
'''

# ohhhhhh yeahhhhh
import telnetlib as tn

import datetime

import time

#from bmjd import Eph

from astrometry.util.file import *
from astrometry.util.starutil_numpy import *
from astrometry.util.fits import *
import sys


'''
earthfromssb-daily.eph:

Ephemeris Type [change] :  VECTORS
Target Body [change] :  Earth [Geocenter] [399]
Coordinate Origin [change] :  Solar System Barycenter (SSB) [500@0]
Time Span [change] :  Start=2003-04-28, Stop=2011-04-26, Step=1 d
Table Settings [change] :  CSV format=YES
Display/Output [change] :  plain text
'''

class Eph(object):
    def __init__(self, fn='earthfromssb-daily.eph', txt=None, linedelim='\n'):
        #self.entries = []
        if txt is not None:
            lines = txt.split(linedelim)
        else:
            lines = read_file(fn).split('\n')
        start = lines.index('$$SOE')
        end = lines.index('$$EOE')
        lines = lines[start+1:end]
        xyz = []
        jds = []
        lts = []
        for line in lines:
            X = line.split(',')
            X = [x.strip() for x in X]
            X = [x for x in X if len(x)]
            jd,ct,x,y,z,vx,vy,vz,lt,rg,rr = X
            x = float(x)
            y = float(y)
            z = float(z)
            jd = float(jd)
            lt = float(lt)
            rg = float(rg)
            lt *= 86400 # days to seconds
            #self.entries.append(jd, ct, x,y,z, lt, rg)
            xyz.append((x,y,z))
            jds.append(jd)
            lts.append(lt)
        self.entries = tabledata()
        self.entries.xyz = np.array(xyz)
        self.entries.jd = np.array(jds)
        self.entries.lt = np.array(lts)

    def get_entries_bounding_jd(self, jd):
        i = self.entries.jd.searchsorted(jd) - 1
        assert(i > 0)
        assert(i < (len(self.entries)-1))
        return self.entries[i], self.entries[i+1]



# Negotiate telnet options.  These ones seemed to be necessary to satisfy JPL c. 2012-02-27
class optcallback(object):
    def __init__(self, debug=False):
        self.debug = debug
    def __call__(self, socket, command, option):
        if self.debug: print('optcallback: socket', socket, 'command #', ord(command), 'option #', ord(option))
        cnum = command
        onum = option
        if cnum == tn.WILL and onum in [ tn.ECHO, tn.SGA ]:
            if self.debug: print('Got WILL', onum)
            if self.debug: print('Sending IAC DO', onum)
            socket.send(tn.IAC + tn.DO + onum)
        elif cnum == tn.WILL:
            if self.debug: print('Got WILL', onum)
            if self.debug: print('Sending IAC DONT', onum)
            socket.send(tn.IAC + tn.DONT + onum)
        elif cnum == tn.DO and onum == tn.NAWS:
            if self.debug: print('Got DO NAWS')
            # 16-bit big-endian W x H (0x00, 0x80) = 128
            reply = (tn.IAC + tn.WILL + tn.NAWS +
                     tn.IAC + tn.SB + tn.NAWS +
                     chr(0) + chr(0x80) + chr(0) + chr(0x80) +
                     tn.IAC + tn.SE)
            if self.debug:
                print('Replying:', reply)
                print(' hex: ', end=' ')
                for c in reply:
                    print('0x%02x' % ord(c), end=' ')
                print()
            socket.send(reply)
        elif cnum == tn.DO and onum == tn.TTYPE:
            if self.debug: print('Got DO TTYPE')
            reply = (tn.IAC + tn.WILL + tn.TTYPE +
                     tn.IAC + tn.SB + tn.TTYPE + chr(0) +
                     'DEC-VT100' +
                     tn.IAC + tn.SE)
            if self.debug:
                print('Replying:', reply)
                print(' hex: ', end=' ')
                for c in reply:
                    print('0x%02x' % ord(c), end=' ')
                print()
            socket.send(reply)
        elif cnum == tn.DO: # and onum == tn.TTYPE:
            if self.debug: print('Got DO', onum)
            if self.debug: print('Sending WONT', onum)
            socket.send(tn.IAC + tn.WONT + onum) #tn.TTYPE)

        
'''
About VT100-speak:

http://www.termsys.demon.co.uk/vtansi.htm
\x1b
7
\x1b
[r
\x1b
[999;999H
                <ESC>[{ROW};{COLUMN}HCursor Home 
\x1b
[6n

Query Cursor Position<ESC>[6n
    Requests a Report Cursor Position response from the device.
    
Report Cursor Position<ESC>[{ROW};{COLUMN}R
    Generated by the device in response to a Query Cursor Position request; reports current cursor position.
        
'''

'''
Telnet options are listed here:
  http://www.iana.org/assignments/telnet-options

Telnet(horizons.jpl.nasa.gov,6775): recv '\xff\xfb\x01'
Telnet(horizons.jpl.nasa.gov,6775): IAC WILL 1

(1: echo)

Telnet(horizons.jpl.nasa.gov,6775): recv '\xff\xfb\x03\xff\xfd\x1f\xff\xfd\x18'
Telnet(horizons.jpl.nasa.gov,6775): IAC WILL 3
Telnet(horizons.jpl.nasa.gov,6775): IAC DO 31
Telnet(horizons.jpl.nasa.gov,6775): IAC DO 24

(3: suppress go-ahead)
(31: negotiate about window size)
(24: terminal type)

    IAC SB NAWS <16-bit value> <16-bit value> IAC SE

    Sent by the Telnet client to inform the Telnet server of the
    window width and height.

    IAC SB TERMINAL-TYPE IS ... IAC SE

'''

def _horizons_login(debug=False):
    t = tn.Telnet('horizons.jpl.nasa.gov', 6775)
    print('Waiting for Horizons...')
    if debug:
        t.set_debuglevel(10)
    '''
    Each time a telnet option is read on the input flow, this callback
    (if set) is called with the following parameters : callback(telnet
    socket, command (DO/DONT/WILL/WONT), option). No other action is
    done afterwards by telnetlib.
    '''
    cb = optcallback(debug=debug)
    t.set_option_negotiation_callback(cb)

    # Horizons used to assume VT100, we think; it used to do:
    # # VT100: how big is your terminal?   '\x1b7\x1b[r\x1b[999;999H\x1b[6n'
    # ESC = chr(0x1b)
    # txt = t.read_until(ESC + '[6n', 30)
    # # big enough!
    # t.write(ESC + '[50;150R')

    if debug: print('Waiting for Horizons prompt')
    txt = t.read_until('Horizons>', 30)
    # Don't do page breaks
    t.write('PAGE\n')
    if debug: print('Waiting for Horizons prompt')
    txt = t.read_until('Horizons>', 30)
    return t

def get_radec_for_jds(bodyname, jd0, jd1, interval='1d', debug=False):
    t = _horizons_login(debug=debug)
    t.write( # Body name; if found, it asks "Continue?"
             '%s\r\n' % bodyname)
    #t.read_until('[A]pproaches, [E]phemeris, [F]tp,')

    #time.sleep(5)
    #txt = t.read_eager()
    #print 'Read', txt
    #time.sleep(1)
    #txt = t.read_eager()
    #print 'Read', txt

    #txt2 = t.read_until('Horizons> ')
    #txt2 = t.read_until('<cr>: ')
    txt=''
    txt2 = t.read_until('<cr>')
    print()
    print('--------------------------------')
    print()
    print(txt, txt2)
    print()
    print('--------------------------------')
    print()
    t.write('\n')

    # if 'EXACT' in txt2:
    #     '''
    #     >EXACT< designation search [CASE & SPACE sensitive]:
    #     DES = C/2014 Q2;
    #     Continue [ <cr>
    #     Telnet(horizons.jpl.nasa.gov,6775): send 'E\r\n'
    #     Telnet(horizons.jpl.nasa.gov,6775): recv ' n=no, ? ] : '
    #     Telnet(horizons.jpl.nasa.gov,6775): recv 'E\r\nContinue [ <cr>=yes, n=no, ? ] : '
    #     '''
    #     #txt = t.read_until('Continue')
    #     txt = t.read_until('Continue [ <cr>=yes,  n=no, ? ] :')
    #     print 'Read', txt
    #     t.write('\n')
        
    # t.write('\n')
    # txt = t.read_until('\nHorizons> ')
    # print txt
    txt = t.read_until('[E]phemeris')
    t.write('E\r\n')
    
    txt = t.read_until('Observe, Elements, Vectors  [o,e,v,?]')
    print(txt)
    t.write('o\n')
    t.read_until('Coordinate center [ <id>,coord,geo  ]')
    t.write('geo\n')
    t.read_until('Starting UT')
    t.write('JD %.9f\n' % jd0)
    t.read_until('Ending   UT')
    t.write('JD %.9f\n' % jd1)
    t.read_until('Output interval [ex: 10m, 1h, 1d, ? ]')
    t.write('%s\n' % interval)
    t.read_until('Accept default output [ cr=(y), n, ?]')
    t.write('\n')
    t.read_until('Select table quantities [ <#,#..>, ?]')
    t.write('1\n')

    # t.write('n\n')
    # t.read_until('Select table quantities')
    # t.write('1\n')
    # t.read_until('Output reference frame')
    # t.write('J2000\n')
    # t.read_until('Time-zone correction')
    # t.write('\n')
    # t.read_until('Output UT time format   [JD,CAL,BOTH]')
    # t.write('JD\n')
    # t.read_until('Output time digits  [MIN,SEC,FRACSEC]')
    # t.write('SEC\n')
    # t.read_until('Output R.A. format       [ HMS, DEG ]')
    # t.write('DEG\n')
    # t.read_until('Output high precision RA/DEC [YES,NO]')
    # t.write('YES\n')
    # t.read_until('Output APPARENT [ Airless,Refracted ]')
    # t.write('Airless\n')
    # t.read_until('Set units for RANGE output [ KM, AU ]')
    # t.write('AU\n')
    # t.read_until('Suppress RANGE_RATE output [ YES,NO ]')
    # t.write('YES\n')
    # t.read_until('Minimum elevation [ -90 <= elv <= 90]')
    # t.write('\n')

    # t.write('n\n')
    # t.read_until('Select table quantities [ <#,#..>, ?]')
    # t.write('1\n')
    # t.read_until('Output reference frame [J2000, B1950]')
    # t.write('J2000\n')
    # t.read_until('Time-zone correction   [ UT=00:00,? ]')
    # t.write('\n')
    # t.read_until('Output UT time format   [JD,CAL,BOTH]')
    # t.write('JD\n')
    # t.read_until('Output time digits  [MIN,SEC,FRACSEC]')
    # t.write('SEC\n')
    # t.read_until('Output R.A. format       [ HMS, DEG ]')
    # t.write('DEG\n')
    # t.read_until('Output high precision RA/DEC [YES,NO]')
    # t.write('YES\n')
    # t.read_until('Output APPARENT [ Airless,Refracted ]')
    # t.write('Airless\n')
    # t.read_until('Set units for RANGE output [ KM, AU ]')
    # t.write('AU\n')
    # t.read_until('Suppress RANGE_RATE output [ YES,NO ]')
    # t.write('YES\n')
    # t.read_until('Minimum elevation [ -90 <= elv <= 90]')
    # t.write('-90\n')

    #txt = t.read_until('Working ...', 10)
    #eph = t.read_until('>>> Select...', 60)

    txt = t.read_until('Ephemeris / PORT_LOGIN')
    header = t.read_until('$$SOE')
    eph = t.read_until('$$EOE')

    print('Header:', header)
    print('Eph:', eph)

    lines = eph.split('\n')
    print('first line:', lines[0])
    print('last line:', lines[-1])
    lines = lines[1:-1]
    print('first line:', lines[0])
    print('last line:', lines[-1])
    
    date,ra,dec = [],[],[]
    for line in lines:
        words = line.split()
        date.append(datetime.datetime.strptime(' '.join(words[:2]), '%Y-%b-%d %H:%M'))
        words = words[2:]
        ra.append(hmsstring2ra(' '.join(words[:3])))
        words = words[3:]
        dec.append(dmsstring2dec(' '.join(words[:3])))
    
    return date, ra, dec
    
    
def get_ephemerides_for_jds(bodyname, jds, debug=False):
    print('JDs:', jds)
    t = _horizons_login()
    ephs = []
    jd = jds[0]
    margin = 1. / (24.*3600.)
    
    print('getting JD', jd)
    t.write( # Body name; if found, it asks "Continue?"
             '%s\n\n' % bodyname +
             # [E]phemeris
             'E\n' +
             # [O]bserve, [E]lements, [V]ectors?
             'v\n' +
             '@0\n' +
             'eclip\n' +
             'JD %.9f\n' % jd +
             'JD %.9f\n' % (jd+margin) +
             '1h\n' +
             'n\nJ2000\n' +
             '1\n' + # corrections = NONE
             '2\n' + # AU/days
             'YES\n' + # CSV format
             'YES\n' + # label cartesian output?
             '3\n')
    txt = t.read_until('Working ...', 10)
    eph = t.read_until('>>> Select...', 60)
    if debug:
        print('Got eph: "%s"' % eph)
    ephs.append(eph)

    for jd in jds[1:]:
        print('getting JD', jd)
        t.write('A\nE\nv\n' +
                '\neclip\n' +
                'JD %.9f\n' % jd +
                'JD %.9f\n' % (jd+margin) +
                '1h\n' +
                '\n'
                )
        eph2 = t.read_until('>>> Select...', 60)
        ephs.append(eph2)
        if debug:
            print('Got eph: "%s"' % eph2)
        
    t.write('q\n')
    t.close()

    if debug:
        print('Got text:')
        for i,txt in enumerate(ephs):
            print('  ', txt)

            fn = 'txt%i' % i
            write_file(txt, fn)
            print('wrote', fn)

    EE = [Eph(txt=txt, linedelim='\r\n') for txt in ephs]
    return EE

if __name__ == '__main__':
    
    import optparse
    parser = optparse.OptionParser()
    parser.add_option('--start', default='2000-1-1',
                      help='Start date, YYYY-M-D, default %default')
    parser.add_option('--end', default='2021-1-1',
                      help='End date, YYYY-M-D, default %default')
    parser.add_option('--interval', default='1d',
                      help='Interval, default %default')
    parser.add_option('--body', default='C/2012 S1',
                      help='Solar system body, default %default')
    parser.add_option('--fits', default='ison-ephem.fits',
                      help='FITS table output filename, default %default')

    parser.add_option('--verbose', '-v', action='store_true', default=False,
                      help='Verbose mode?')
    
    opt,args = parser.parse_args()

    date0 = opt.start.split('-')
    if len(date0) != 3:
        print('Expected YYYY-M-D, got', opt.start)
        sys.exit(-1)
    date0 = [int(x, 10) for x in date0]
    date0 = datetime.datetime(*date0)
    print('Start date:', date0)
    jd0 = datetojd(date0)
    print('Start JD:', jd0)

    date1 = opt.end.split('-')
    if len(date1) != 3:
        print('Expected YYYY-M-D, got', opt.end)
        sys.exit(-1)
    date1 = [int(x, 10) for x in date1]
    date1 = datetime.datetime(*date1)
    print('End date:', date1)
    jd1 = datetojd(date1)
    print('End JD:', jd1)

    date,ra,dec = get_radec_for_jds(opt.body, jd0, jd1, debug=opt.verbose,
                                    interval=opt.interval)
    for d,rr,dd in zip(date, ra, dec):
        print('  ', d, rr, dd)

    T = fits_table()
    T.jd  = np.array([datetojd(d) for d in date])
    T.ra  = np.array(ra)
    T.dec = np.array(dec)
    T.writeto(opt.fits)
    print('Wrote', opt.fits)

    sys.exit(0)
    
    # import numpy as np
    # jd = 2454153.93624056 + np.random.normal(size=10)*300.
    # ephs = get_ephemerides_for_jds('GALEX', jd)
    # for j,E in zip(jd,ephs):
    #   E = E.entries[0]
    #   print
    #   print j
    #   print E.jd, E.lt, E.xyz
    
    jd0 = datetojd(datetime.datetime(2013,  9,  1))
    #jd1 = datetojd(datetime.datetime(2014,  3, 31))
    jd1 = datetojd(datetime.datetime(2014,  1,  1))
    print('jds', jd0, jd1)
    date,ra,dec = get_radec_for_jds('C/2012 S1', jd0, jd1, debug=True,
                                    interval='1h')
    
    for d,r,dd in zip(date, ra, dec):
        print('  ', d, r, dd)

    T = fits_table()
    T.jd  = np.array([datetojd(d) for d in date])
    T.ra  = np.array(ra)
    T.dec = np.array(dec)
    T.writeto('ison-ephem.fits')
