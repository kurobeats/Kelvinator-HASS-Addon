#include <stdio.h>
#include <stdarg.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
int __android_log_write(int prio, const char *tag, const char *text) { fprintf(stderr, "[log/%d] %s: %s\n", prio, tag?tag:"", text?text:""); return 0; }
int __android_log_print(int prio, const char *tag, const char *fmt, ...) {
    va_list ap; va_start(ap, fmt);
    fprintf(stderr, "[log/%d] %s: ", prio, tag?tag:"");
    vfprintf(stderr, fmt, ap);
    fprintf(stderr, "\n");
    va_end(ap); return 0;
}
int __android_log_vprint(int prio, const char *tag, const char *fmt, va_list ap) {
    fprintf(stderr, "[log/%d] %s: ", prio, tag?tag:""); vfprintf(stderr, fmt, ap); fprintf(stderr, "\n"); return 0;
}
int __android_log_buf_print(int buf, int prio, const char *tag, const char *fmt, ...) {
    va_list ap; va_start(ap, fmt);
    fprintf(stderr, "[log/%d/%d] %s: ", buf, prio, tag?tag:""); vfprintf(stderr, fmt, ap); fprintf(stderr, "\n"); va_end(ap); return 0;
}
int __android_log_buf_write(int buf, int prio, const char *tag, const char *text) { return __android_log_write(prio, tag, text); }
int __android_log_is_loggable(int prio, const char *tag, int def) { return 1; }
void __assert2(const char *file, int line, const char *func, const char *expr) { fprintf(stderr,"ASSERT %s:%d %s %s\n", file, line, func?func:"", expr?expr:""); abort(); }
int *__errno(void) { return &errno; }
char __sF[3 * 0xe0];
__attribute__((constructor)) static void fillsf(void) {
    memcpy(__sF, stdin, sizeof(*stdin));
    memcpy(__sF + 0xe0, stdout, sizeof(*stdout));
    memcpy(__sF + 2 * 0xe0, stderr, sizeof(*stderr));
}
