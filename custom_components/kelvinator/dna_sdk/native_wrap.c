#include <string.h>
/* wrapper */
/* ---- fake JNIEnv ---- */
typedef const void *JNIEnv;   /* points at cell holding vtable */
static void *g_table[256];
static void *g_env_cell[1];

static void *gsuc(void *env, const char *js, unsigned char *isCopy) {
    if (isCopy) *isCopy = 0;
    return (void *)js;
}
static void *nsu(void *env, const char *s) { return s ? (void *)strdup(s) : 0; }
static void relv(void *env, const char *js, const char *c) { (void)js; (void)c; }
static void *noop(void *env, void *a, void *b) { return 0; }

static void init_vtable(void) {
    for (int i = 0; i < 256; i++) g_table[i] = (void *)noop;
    g_table[167] = (void *)nsu;   /* NewStringUTF */
    g_table[169] = (void *)gsuc;  /* GetStringUTFChars */
    g_table[170] = (void *)relv;  /* ReleaseStringUTFChars */
    g_env_cell[0] = g_table;
}

extern void *Java_cn_com_broadlink_networkapi_NetworkAPI_SDKInit(void*, void*, const char*);
extern void *Java_cn_com_broadlink_networkapi_NetworkAPI_dnaControl(void*, void*, const char*, const char*, const char*, const char*);
extern void *Java_cn_com_broadlink_networkapi_NetworkAPI_bl_1sdk_1auth(void*, void*,
    const char*,const char*,const char*,const char*,const char*,const char*,const char*,
    const char*,const char*,const char*,const char*,const char*,const char*);

const char *dna_sdk_init(const char *config) {
    init_vtable();
    return (const char *)Java_cn_com_broadlink_networkapi_NetworkAPI_SDKInit(g_env_cell, 0, config);
}
const char *dna_sdk_auth(const char **p) {
    init_vtable();
    return (const char *)Java_cn_com_broadlink_networkapi_NetworkAPI_bl_1sdk_1auth(
        g_env_cell, 0, p[0],p[1],p[2],p[3],p[4],p[5],p[6],p[7],p[8],p[9],p[10],p[11],p[12]);
}
const char *dna_sdk_ctrl(const char *dev, const char *sub, const char *data, const char *desc) {
    init_vtable();
    return (const char *)Java_cn_com_broadlink_networkapi_NetworkAPI_dnaControl(
        g_env_cell, 0, dev, sub, data, desc);
}
