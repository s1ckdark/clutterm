from gi.repository import Clutter
from time import time
from .shell import Shell, ReaderAsync
from .shader import shaders, apply_glsl_effect
from .bindings import special_keys, ctrl_special_keys
from .lex import Lexer

import logging
log = logging.getLogger('clutterm')


class Clutterm(object):

    def __init__(self, options):
        """
        Build the user interface.
        """
        self.itime = time()
        self.shader = None
        self.destroyed = False
        self.font = "%s %s" % (options.font_name, options.font_size)
        self.size = None, None
        self.mainStage = Clutter.Stage.get_default()
        self.mainStage.set_title("Clutterm")
        self.mainStage.set_reactive(True)
        self.mainStage.set_user_resizable(True)
        if options.transparency > 0:
            self.mainStage.set_use_alpha(True)
        self.mainStage.set_color(
            Clutter.Color.new(0, 0, 0, 255 - options.transparency))

        # Create lines group
        self.linesGroup = Clutter.Group()
        self.mainStage.add_actor(self.linesGroup)
        dummy_text = Clutter.Text()
        dummy_text.set_font_name(self.font)
        dummy_text.set_text("#")
        self.char_width = dummy_text.get_width()
        self.char_height = dummy_text.get_height()
        self.shell = Shell(options, end_callback=self.destroy)
        self.lexer = Lexer(self.shell.cols, self.shell.rows,
                           self.set_title, self.bell)

        self.cursor = Clutter.Rectangle()
        self.cursor.set_color(Clutter.Color.new(255, 255, 255, 100))
        self.cursor.set_x(self.char_width * self.lexer.cursor.x)
        self.cursor.set_y(self.char_height * self.lexer.cursor.y)
        self.cursor.set_width(self.char_width)
        self.cursor.set_height(self.char_height)
        self.mainStage.add_actor(self.cursor)

        def create_line(i):
            line = Clutter.Text()
            # We must never see this color:
            line.set_color(Clutter.Color.new(255, 0, 255, 255))
            line.set_font_name(self.font)
            line.set_width(self.char_width * self.shell.cols)
            line.set_height(self.char_height)
            line.set_y(i * self.char_height)
            self.linesGroup.add_actor(line)
            return line

        def resize(w, h):
            w = self.mainStage.get_width()
            h = self.mainStage.get_height()
            cols = int(w / self.char_width)
            rows = int(h / self.char_height)
            if (cols, rows) == (self.lexer.matrix.cols, self.shell.rows):
                return
            log.info('resize %s %s %s %s' % (w, h, cols, rows))
            self.shell.resize(cols, rows)
            self.lexer.resize(cols, rows)
            self.linesGroup.set_geometry(self.mainStage.get_geometry())
            for line in self.lines:
                self.linesGroup.remove_actor(line)
            self.lines = [create_line(i)
                          for i in range(self.shell.rows)]

        self.lines = [create_line(i)
                      for i in range(self.shell.rows)]

        self.thread = ReaderAsync(self.shell, self.write, self.destroy)
        self.thread.start()

        # Clutter.threads_add_timeout(300, 40, self.tick, None)
        # Setup key bindings on the terminal
        self.mainStage.connect_after("key-press-event", self.onKeyPress)
        self.mainStage.connect_after("notify::width", resize)
        self.mainStage.connect_after("notify::height", resize)
        self.mainStage.set_size(
            self.shell.cols * self.char_width,
            self.shell.rows * self.char_height)
        self.linesGroup.set_geometry(self.mainStage.get_geometry())
        # Present the main stage (and make sure everything is shown)
        self.mainStage.show_all()

    def write(self, text):
        if text == '':
            return

        self.lexer.lex(text)
        for line in self.lexer.damaged:
            if __debug__:
                log.debug('Setting line: %d' % line)
            self.set_line(line, self.lexer.get_line(line))
        self.lexer.damaged = set()

        self.cursor.animatev(
            Clutter.AnimationMode.LINEAR, 50,
            (
                "x",
                "y"
            ), (
                self.char_width * self.lexer.cursor.x,
                self.char_height * self.lexer.cursor.y
            )
        )

    def set_title(self, text):
        self.mainStage.set_title(text)

    def bell(self):
        self.linesGroup.animatev(
            Clutter.AnimationMode.EASE_OUT_BACK, 100,
            (
                "fixed::scale-x",
                "fixed::scale-y",
                "fixed::scale-center-x",
                "fixed::scale-center-y",
                "scale-x",
                "scale-y"
            ), (
                1.2,
                1.2,
                self.linesGroup.get_width() / 2,
                self.linesGroup.get_height() / 2,
                1,
                1
            )
        )

    def set_line(self, line, text):
        if __debug__:
            log.debug("D%d %r" % (line, text))
        self.lines[line].set_markup(text)

    def tick(self, _):
        if self.shader:
            self.shader.set_uniform_value(
                'time', time() - self.itime)
        return True

    def destroy(self):
        if not self.destroyed:
            log.info('Quitting main')
            Clutter.main_quit()
            self.destroyed = True

    def onKeyPress(self, actor=None, event=None, data=None):
        """
        Basic key binding handler
        """
        uval = event.unicode_value
        kval = event.keyval
        state = event.modifier_state

        log.debug('u %r v %d' % (uval, kval))

        if uval != '':
            self.shell.write(uval)
            return

        if (state & state.MOD1_MASK == state.MOD1_MASK):
            # Alt key is on putting escape
            self.shell.write('')

        if kval == 65513 or kval == 65507:
            # Alt key will be put later
            return

        if (state & state.SHIFT_MASK == state.SHIFT_MASK):
            if kval in shaders:
                self.shader = None
                shaders[kval](self.linesGroup)
                return

            if kval == 65475:
                self.shader = apply_glsl_effect(self.linesGroup)
                return

            elif kval == 65478:
                from pprint import pprint
                pprint(self.lexer.matrix.matrix)

            elif kval == 65479:
                log.error(
                    '\n'.join(
                        [self.lexer.get_line(line)
                         for line in range(self.lexer.rows)]))

            elif kval == 65480:
                import pdb
                pdb.pm()

            elif kval == 65481:
                import pdb
                pdb.set_trace()

        if kval in special_keys:
            if (state & state.CONTROL_MASK == state.CONTROL_MASK):
                self.shell.write(ctrl_special_keys[kval])
            else:
                self.shell.write(special_keys[kval])
            return

        log.warn('Unknown keyval %d' % kval)
