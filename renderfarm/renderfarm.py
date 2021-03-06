#!/usr/bin/python

import os, sys, threading, time

# Dimensions for recommended povray rendering, gotten from the first line
# of any of the *.pov files.
recommended_width, recommended_height = 751, 459
povray_aspect_ratio = (1. * recommended_width) / recommended_height

# Bit rate of the MPEG stream in bits per second. For 30 FPS video at
# 600x450, 2 mbits/sec looks good and gives a file size of about 250
# Kbytes per second of video. At 1.5 mbits/sec you start to see some
# MPEG artifacts, with file size of 190 Kbytes per second of video.
bitrate = 5.0e6

# Google Video uses a 4:3 aspect ratio because that's what is specified
# below in the MPEG parameter file.
video_aspect_ratio = 4.0 / 3.0

ntsc = True

# mpeg_height and mpeg_width must both be even to make mpeg2encode
# happy. NTSC is 4:3 with resolution 704x480, with non-square pixels.
# I don't know if ImageMagick handles non-square pixels.
def even(x): return int(x) & -2
if ntsc:
    povray_height = 480
    povray_width = int(povray_aspect_ratio * povray_height)
    mpeg_width = 704
    mpeg_height = 480
else:
    # Quick little pictures of much lower resolution
    mpeg_height = 240
    mpeg_width = even(video_aspect_ratio * mpeg_height)
    povray_height = mpeg_height
    povray_width = int(povray_aspect_ratio * povray_height)

worker_list = [
    ('localhost', '/tmp/mpeg'),
    ('server', '/tmp/mpeg'),
    ('laptop', '/tmp/mpeg'),
    ('mac', '/Users/wware/tmp')
    ]

framelimit = None

####################
#                  #
#   DEBUG STUFF    #
#                  #
####################

DEBUG = False

def linenum(*args):
    try:
        raise Exception
    except:
        tb = sys.exc_info()[2]
        f = tb.tb_frame.f_back
        print f.f_code.co_filename, f.f_code.co_name, f.f_lineno,
    if len(args) > 0:
        print ' --> ',
        for x in args:
            print x,
    print

def do(cmd, howfarback=0):
    if DEBUG:
        if False:
            try:
                raise Exception
            except:
                tb = sys.exc_info()[2]
                f = tb.tb_frame.f_back
                for i in range(howfarback):
                    f = f.f_back
                print f.f_code.co_filename, f.f_code.co_name, f.f_lineno
        print cmd
    if os.system(cmd) != 0:
        raise Exception(cmd)

############################
#                          #
#    DISTRIBUTED POVRAY    #
#                          #
############################

_which_povray_job = 0

class PovrayJob:
    def __init__(self, srcdir, dstdir, povfmt, povmin, povmax_plus_one, yuv,
                 pwidth, pheight, ywidth, yheight, textlist):

        assert povfmt[-4:] == '.pov'
        assert yuv[-4:] == '.yuv'
        self.srcdir = srcdir
        self.dstdir = dstdir
        self.povfmt = povfmt
        self.povmin = povmin
        self.povmax_plus_one = povmax_plus_one
        self.yuv = yuv
        self.pwidth = pwidth
        self.pheight = pheight
        self.ywidth = ywidth
        self.yheight = yheight
        self.textlist = textlist

    def go(self, machine, workdir):

        local = machine in ('localhost', '127.0.0.1')

        def worker_do(cmd):
            if DEBUG: print '[[%s]]' % machine,
            if local:
                # do stuff on this machine
                do(cmd, howfarback=1)
            else:
                # do stuff on a remote machine
                do('ssh %s "%s"' % (machine, cmd), howfarback=1)

        worker_do('mkdir -p ' + workdir)
        # worker_do('find %s -type f -exec rm -f {} \;' % workdir)

        #
        # Create a shell script to run on the worker machine
        #
        global _which_povray_job
        self.scriptname = 'povray_job_%08d.sh' % _which_povray_job
        _which_povray_job += 1
        w2 = int(video_aspect_ratio * self.pheight)
        jpg = (self.povfmt % self.povmin)[:-4] + '.jpg'
        tgalist = ''
        povlist = ''
        shellscript = open(os.path.join(self.srcdir, self.scriptname), 'w')
        shellscript.write('cd %s\n' % workdir)
        # Worker machine renders a bunch of pov files to tga files
        for i in range(self.povmin, self.povmax_plus_one):
            pov = self.povfmt % i
            povlist += ' ' + pov
            tga = pov[:-4] + '.tga'
            tgalist += ' ' + tga
            shellscript.write('povray +I%s +O%s +FT +A +W%d +H%d -V -D +X 2>/dev/null\n' %
                              (pov, tga, self.pwidth, self.pheight))
        # Worker machine averages the tga files into one jpeg file
        shellscript.write('convert -average %s -crop %dx%d+%d+0 -geometry %dx%d! %s\n' %
                          (tgalist, w2, self.pheight, (self.pwidth - w2) / 2,
                           self.ywidth, self.yheight, jpg))
        # Worker cleans up the pov and tga files, no longer needed
        shellscript.write('rm -f %s %s\n' %
                          (povlist, tgalist))
        shellscript.close()

        #
        # Copy shell script and pov files to worker
        #
        if local:
            cmd = ('(cd %s; tar cf - %s %s) | (cd %s; tar xf -)' %
                   (self.srcdir, self.scriptname, povlist, workdir))
        else:
            cmd = ('(cd %s; tar cf - %s %s) | gzip | ssh %s "(cd %s; gunzip | tar xf -)"' %
                   (self.srcdir, self.scriptname, povlist, machine, workdir))
        do(cmd)
        do('rm -f ' + os.path.join(self.srcdir, self.scriptname))
        worker_do('chmod +x ' + os.path.join(workdir, self.scriptname))

        #
        # Run the shell script on the worker
        #
        worker_do(os.path.join(workdir, self.scriptname))

        #
        # Retrieve finished image file back from worker
        #
        if DEBUG: print '[[%s]]' % machine,
        if local:
            do('cp %s %s' % (src, dst))
        else:
            do('scp %s:%s %s' % (machine, src, dst))

        #
        # Put text on finished image, and convert to YUV
        #
        if self.textlist:
            cmd = ('convert %s -font times-roman -pointsize 30' %
                   (os.path.join(self.dstdir, jpg)))
            for i in range(len(self.textlist)):
                cmd += ' -annotate +10+%d "%s"' % (30 * (i + 1), self.textlist[i])
            cmd += ' ' + os.path.join(self.dstdir, self.yuv)
            do(cmd)
        else:
            do('convert %s %s' %
               (os.path.join(self.dstdir, jpg),
                os.path.join(self.dstdir, self.yuv)))
        do('rm -f %s' % os.path.join(self.dstdir, jpg))

        #
        # Clean up remaining files on the worker machine
        #
        worker_do('rm -f %s %s' %
                  (os.path.join(workdir, self.scriptname),
                   os.path.join(workdir, jpg)))

all_workers_stop = False

class Worker(threading.Thread):

    def __init__(self, jobqueue, machine, workdir):
        threading.Thread.__init__(self)
        self.machine = machine
        self.jobqueue = jobqueue
        self.workdir = workdir
        self.busy = True

    #
    # Each worker grabs a new jobs as soon as he finishes the previous
    # one. This allows mixing of slower and faster worker machines; each
    # works at capacity.
    #
    def run(self):
        global all_workers_stop
        while not all_workers_stop:
            job = self.jobqueue.get()
            if job is None:
                # no jobs left in the queue, we're finished
                self.busy = False
                return
            try:
                job.go(self.machine, self.workdir)
            except:
                all_workers_stop = True
                raise

class PovrayJobQueue:

    def __init__(self):
        self.worker_pool = [ ]
        self.jobqueue = [ ]
        self._lock = threading.Lock()
        for machine, workdir in worker_list:
            self.worker_pool.append(Worker(self, machine, workdir))

    def append(self, job):
        self._lock.acquire()   # thread safety
        self.jobqueue.append(job)
        self._lock.release()
    def get(self):
        self._lock.acquire()   # thread safety
        try:
            r = self.jobqueue.pop(0)
        except IndexError:
            r = None
        self._lock.release()
        return r

    def start(self):
        for worker in self.worker_pool:
            worker.start()
    def wait(self):
        busy_workers = 1
        while busy_workers > 0:
            time.sleep(0.5)
            busy_workers = 0
            for worker in self.worker_pool:
                if worker.busy:
                    busy_workers += 1
            if all_workers_stop:
                raise Exception
        #for machine, workdir in worker_list:
        #    # clean up all work files
        #    do('ssh %s "find %s -type f -exec rm -f {} \;"' % (machine, workdir))

####################
#                  #
#    MPEG STUFF    #
#                  #
####################

params = """MPEG-2 Test Sequence, 30 frames/sec
%(sourcefileformat)s    /* name of source files */
-         /* name of reconstructed images ("-": don't store) */
-         /* name of intra quant matrix file     ("-": default matrix) */
-         /* name of non intra quant matrix file ("-": default matrix) */
stat.out  /* name of statistics file ("-": stdout ) */
1         /* input picture file format: 0=*.Y,*.U,*.V, 1=*.yuv, 2=*.ppm */
%(frames)d       /* number of frames */
0         /* number of first frame */
00:00:00:00 /* timecode of first frame */
15        /* N (# of frames in GOP) */
3         /* M (I/P frame distance) */
0         /* ISO/IEC 11172-2 stream */
0         /* 0:frame pictures, 1:field pictures */
%(width)d       /* horizontal_size */
%(height)d       /* vertical_size */
2         /* aspect_ratio_information 1=square pel, 2=4:3, 3=16:9, 4=2.11:1 */
5         /* frame_rate_code 1=23.976, 2=24, 3=25, 4=29.97, 5=30 frames/sec. */
%(bitrate)f  /* bit_rate (bits/s) */
112       /* vbv_buffer_size (in multiples of 16 kbit) */
0         /* low_delay  */
0         /* constrained_parameters_flag */
4         /* Profile ID: Simple = 5, Main = 4, SNR = 3, Spatial = 2, High = 1 */
8         /* Level ID:   Low = 10, Main = 8, High 1440 = 6, High = 4 */
0         /* progressive_sequence */
1         /* chroma_format: 1=4:2:0, 2=4:2:2, 3=4:4:4 */
2         /* video_format: 0=comp., 1=PAL, 2=NTSC, 3=SECAM, 4=MAC,
5=unspec. */
5         /* color_primaries */
5         /* transfer_characteristics */
4         /* matrix_coefficients */
%(width)d       /* display_horizontal_size */
%(height)d       /* display_vertical_size */
0         /* intra_dc_precision (0: 8 bit, 1: 9 bit, 2: 10 bit, 3: 11 bit */
1         /* top_field_first */
0 0 0     /* frame_pred_frame_dct (I P B) */
0 0 0     /* concealment_motion_vectors (I P B) */
1 1 1     /* q_scale_type  (I P B) */
1 0 0     /* intra_vlc_format (I P B)*/
0 0 0     /* alternate_scan (I P B) */
0         /* repeat_first_field */
0         /* progressive_frame */
0         /* P distance between complete intra slice refresh */
0         /* rate control: r (reaction parameter) */
0         /* rate control: avg_act (initial average activity) */
0         /* rate control: Xi (initial I frame global complexity measure) */
0         /* rate control: Xp (initial P frame global complexity measure) */
0         /* rate control: Xb (initial B frame global complexity measure) */
0         /* rate control: d0i (initial I frame virtual buffer fullness) */
0         /* rate control: d0p (initial P frame virtual buffer fullness) */
0         /* rate control: d0b (initial B frame virtual buffer fullness) */
2 2 11 11 /* P:  forw_hor_f_code forw_vert_f_code search_width/height */
1 1 3  3  /* B1: forw_hor_f_code forw_vert_f_code search_width/height */
1 1 7  7  /* B1: back_hor_f_code back_vert_f_code search_width/height */
1 1 7  7  /* B2: forw_hor_f_code forw_vert_f_code search_width/height */
1 1 3  3  /* B2: back_hor_f_code back_vert_f_code search_width/height */
"""


# Where will I keep all my temporary files? On Mandriva, /tmp is small
# but $HOME/tmp is large.
mpeg_dir = '/home/wware/tmp/mpeg'

class MpegSequence:

    def __init__(self, bitrate):
        self.bitrate = bitrate
        self.frame = 0
        self.width = mpeg_width
        self.height = mpeg_height
        self.size = (self.width, self.height)
        do("rm -rf " + mpeg_dir + "/yuvs")
        do("mkdir -p " + mpeg_dir + "/yuvs")

    def __len__(self):
        return self.frame

    def yuv_format(self):
        # Leave off the ".yuv" so we can use it for the
        # mpeg2encode parameter file.
        return mpeg_dir + '/yuvs/foo.%06d'

    def yuv_name(self, i=None):
        if i is None:
            i = self.frame
        return (self.yuv_format() % i) + '.yuv'

    # By default, each title page stays up for five seconds
    def titleSequence(self, titlefile, frames=150):
        assert os.path.exists(titlefile)
        if framelimit is not None: frames = min(frames, framelimit)
        first_yuv = self.yuv_name()
        do('convert -geometry %dx%d! %s %s' %
           (self.width, self.height, titlefile, first_yuv))
        self.frame += 1
        for i in range(1, frames):
            import shutil
            shutil.copy(first_yuv, self.yuv_name())
            self.frame += 1

    def previouslyComputed(self, fmt, frames, begin=0):
        assert os.path.exists(titlefile)
        if framelimit is not None: frames = min(frames, framelimit)
        for i in range(frames):
            import shutil
            src = fmt % (i + begin)
            shutil.copy(src, self.yuv_name())
            self.frame += 1

    def nanosecond_format(self, psecs_per_frame):
        if psecs_per_frame >= 10.0:
            return '%.0f nanoseconds'
        elif psecs_per_frame >= 1.0:
            return '%.1f nanoseconds'
        elif psecs_per_frame >= 0.1:
            return '%.2f nanoseconds'
        elif psecs_per_frame >= 0.01:
            return '%.3f nanoseconds'
        else:
            return '%.4f nanoseconds'

    def motionBlurSequence(self, povfmt, frames, psecs_per_subframe,
                           ratio, avg, begin=0):
        # avg is how many subframes are averaged to produce each frame
        # ratio is the ratio of subframes to frames
        if framelimit is not None: frames = min(frames, framelimit)
        pq = PovrayJobQueue()
        nfmt = self.nanosecond_format(ratio * psecs_per_subframe)
        yuvs = [ ]
        srcdir, povfmt = os.path.split(povfmt)

        for i in range(frames):
            yuv = self.yuv_name()
            yuvs.append(yuv)
            dstdir, yuv = os.path.split(yuv)
            nsecs = 0.001 * i * ratio * psecs_per_subframe
            textlist = [
                nfmt % nsecs,
                # Rotation of small bearing at 5 GHz
                '%.3f rotations' % (nsecs / 0.2),
                '%.1f degrees' % (360. * nsecs / 0.2)
                ]
            job = PovrayJob(srcdir, dstdir, povfmt,
                            begin + i * ratio,
                            begin + i * ratio + avg,
                            yuv,
                            povray_width, povray_height,
                            mpeg_width, mpeg_height, textlist)
            pq.append(job)
            self.frame += 1
        pq.start()
        pq.wait()

    def encode(self):
        parfil = mpeg_dir + "/foo.par"
        outf = open(parfil, "w")
        outf.write(params % {'sourcefileformat': self.yuv_format(),
                             'frames': len(self),
                             'height': self.height,
                             'width': self.width,
                             'bitrate': self.bitrate})
        outf.close()
        # encoding is an inexpensive operation, do it even if not for real
        do('mpeg2encode %s/foo.par %s/foo.mpeg' % (mpeg_dir, mpeg_dir))


###################################################


def example_usage():
    m = MpegSequence(bitrate)
    m.titleSequence('title1.gif')
    m.titleSequence('title2.gif')
    m.motionBlurSequence(os.path.join(mpeg_dir, 'fastpov/fast.%06d.pov'),
                         450, 0.0005, 10, 10)
    m.titleSequence('title3.gif')
    m.motionBlurSequence(os.path.join(mpeg_dir, 'medpov/med.%06d.pov'),
                         450, 0.002, 10, 10)
    m.titleSequence('title4.gif')
    m.motionBlurSequence(os.path.join(mpeg_dir, 'slowpov/slow.%06d.pov'),
                         450, 0.02, 10, 10)
    m.encode()

'''
Example usages:

python -c "import animate; animate.example_usage()"
python -c "import animate; animate.framelimit=4;
animate.example_usage()"
python -c "import animate; animate.DEBUG=True; animate.example_usage()"

or you could write a script that imports and uses this stuff.
'''

