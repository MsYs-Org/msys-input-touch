#define _GNU_SOURCE

#include "msys/mipc.h"
#include "msys_ui/document.h"
#include "msys_ui/fonts.h"
#include "msys_ui/runtime.h"
#include "msys_ui/theme.h"

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define MAX_KEYS 48U
#define MAX_CANDIDATES 8U
#define INPUT_BUFFER 16384U

typedef struct keyboard keyboard_t;

typedef struct {
    keyboard_t *owner;
    char token[40];
    lv_obj_t *button;
} key_view_t;

struct keyboard {
    msys_ui_runtime_t *runtime;
    msys_ui_surface_t *surface;
    msys_ui_theme_t *theme;
    msys_ui_document_t *document;
    const msys_ui_anim_policy_t *policy;
    lv_obj_t *screen;
    lv_obj_t *mode_label;
    lv_obj_t *composition;
    lv_obj_t *candidates;
    lv_obj_t *keys;
    key_view_t hide_view;
    key_view_t key_views[MAX_KEYS];
    size_t key_count;
    size_t layout_key_count;
    char mode[16];
    bool shift;
    bool visible;
    bool standalone;
    uint64_t stop_at_ms;
    char input[INPUT_BUFFER];
    size_t input_used;
};

static keyboard_t *active_keyboard;

static uint64_t monotonic_ms(void)
{
    struct timespec now;
    if(clock_gettime(CLOCK_MONOTONIC, &now) != 0) return 0U;
    return (uint64_t)now.tv_sec * 1000U + (uint64_t)now.tv_nsec / 1000000U;
}

static void signal_cb(int signal_number)
{
    (void)signal_number;
    if(active_keyboard != NULL)
        msys_ui_runtime_stop(active_keyboard->runtime);
}

static void font(keyboard_t *keyboard, lv_obj_t *label, uint16_t pixels)
{
    lv_obj_set_style_text_font(label,
                               msys_ui_theme_font(keyboard->theme, pixels),
                               LV_PART_MAIN);
}

static bool json_string(const char *json, const char *key, char *output,
                        size_t capacity)
{
    size_t length = 0U;
    return msys_mipc_json_get_string(json, key, output, capacity, &length) ==
           MSYS_MIPC_OK;
}

static bool json_bool(const char *json, const char *key)
{
    const char *raw = NULL;
    size_t length = 0U;
    return msys_mipc_json_get_raw(json, key, &raw, &length) == MSYS_MIPC_OK &&
           length == 4U && memcmp(raw, "true", 4U) == 0;
}

static int json_escape(char *output, size_t capacity, const char *value)
{
    const unsigned char *cursor = (const unsigned char *)value;
    size_t used = 0U;
    if(capacity < 3U) return -1;
    output[used++] = '"';
    while(*cursor != '\0') {
        if(*cursor < 0x20U || *cursor == 0x7fU) return -1;
        if(*cursor == '"' || *cursor == '\\') {
            if(used + 2U >= capacity) return -1;
            output[used++] = '\\';
        }
        else if(used + 1U >= capacity)
            return -1;
        output[used++] = (char)*cursor++;
    }
    if(used + 2U > capacity) return -1;
    output[used++] = '"';
    output[used] = '\0';
    return 0;
}

static void emit_token(const char *token)
{
    char escaped[128];
    if(json_escape(escaped, sizeof(escaped), token) != 0) return;
    (void)fprintf(stdout, "{\"type\":\"token\",\"token\":%s}\n",
                  escaped);
    (void)fflush(stdout);
}

static void key_event_cb(lv_event_t *event)
{
    key_view_t *view = lv_event_get_user_data(event);
    lv_event_code_t code = lv_event_get_code(event);
    if(view == NULL || view->owner == NULL) return;
    if(code == LV_EVENT_PRESSED)
        msys_ui_animate_press(view->button, view->owner->policy, true);
    else if(code == LV_EVENT_RELEASED || code == LV_EVENT_PRESS_LOST)
        msys_ui_animate_press(view->button, view->owner->policy, false);
    else if(code == LV_EVENT_CLICKED)
        emit_token(view->token);
}

static lv_obj_t *add_key(keyboard_t *keyboard, lv_obj_t *row,
                         const char *token, const char *label, int weight,
                         bool accent)
{
    key_view_t *view;
    lv_obj_t *button;
    lv_obj_t *text;
    if(keyboard->key_count >= MAX_KEYS) return NULL;
    view = &keyboard->key_views[keyboard->key_count++];
    memset(view, 0, sizeof(*view));
    view->owner = keyboard;
    (void)snprintf(view->token, sizeof(view->token), "%s", token);
    button = lv_button_create(row);
    view->button = button;
    lv_obj_add_style(button, msys_ui_theme_button(keyboard->theme),
                     LV_PART_MAIN);
    lv_obj_set_height(button, LV_PCT(100));
    lv_obj_set_flex_grow(button, weight);
    lv_obj_set_style_pad_all(button, 1, LV_PART_MAIN);
    lv_obj_set_style_bg_color(button,
                              lv_color_hex(accent ? 0x3f66e8 : 0xedf1f7),
                              LV_PART_MAIN);
    lv_obj_set_style_text_color(button,
                                lv_color_hex(accent ? 0xffffff : 0x182033),
                                LV_PART_MAIN);
    text = lv_label_create(button);
    lv_label_set_text(text, label);
    font(keyboard, text, 14);
    lv_obj_center(text);
    lv_obj_add_event_cb(button, key_event_cb, LV_EVENT_ALL, view);
    return button;
}

static lv_obj_t *make_row(keyboard_t *keyboard)
{
    lv_obj_t *row = lv_obj_create(keyboard->keys);
    lv_obj_remove_style_all(row);
    lv_obj_set_width(row, LV_PCT(100));
    lv_obj_set_flex_grow(row, 1);
    lv_obj_set_style_pad_gap(row, 2, LV_PART_MAIN);
    lv_obj_set_flex_flow(row, LV_FLEX_FLOW_ROW);
    return row;
}

static void add_letters(keyboard_t *keyboard, lv_obj_t *row,
                        const char *letters)
{
    char token[16] = "char:x";
    char label[2] = {'x', '\0'};
    const char *cursor;
    for(cursor = letters; *cursor != '\0'; cursor++) {
        char value = keyboard->shift && *cursor >= 'a' && *cursor <= 'z'
                         ? (char)(*cursor - ('a' - 'A'))
                         : *cursor;
        token[5] = *cursor;
        label[0] = value;
        (void)add_key(keyboard, row, token, label, 1, false);
    }
}

static void build_letter_layout(keyboard_t *keyboard)
{
    lv_obj_t *row;
    row = make_row(keyboard);
    add_letters(keyboard, row, "qwertyuiop");
    row = make_row(keyboard);
    add_letters(keyboard, row, "asdfghjkl");
    row = make_row(keyboard);
    (void)add_key(keyboard, row, "shift", LV_SYMBOL_UP, 2, keyboard->shift);
    add_letters(keyboard, row, "zxcvbnm");
    (void)add_key(keyboard, row, "backspace", LV_SYMBOL_BACKSPACE, 2, false);
    row = make_row(keyboard);
    (void)add_key(keyboard, row, "mode:numeric", "123", 2, false);
    (void)add_key(keyboard, row,
                  strcmp(keyboard->mode, "zh") == 0 ? "mode:en" : "mode:zh",
                  strcmp(keyboard->mode, "zh") == 0 ? "EN" : "中", 2, true);
    (void)add_key(keyboard, row, "char:,", ",", 1, false);
    (void)add_key(keyboard, row, "space", "空格", 4, false);
    (void)add_key(keyboard, row, "char:.", ".", 1, false);
    (void)add_key(keyboard, row, "enter", LV_SYMBOL_NEW_LINE, 2, true);
}

static void build_numeric_layout(keyboard_t *keyboard, bool symbols)
{
    static const char *number_rows[] = {"12345", "67890", "-/:;()"};
    static const char *symbol_rows[] = {"!@#$%", "^&*+=", "[]{}<>"};
    const char **rows = symbols ? symbol_rows : number_rows;
    size_t index;
    for(index = 0U; index < 3U; index++) {
        lv_obj_t *row = make_row(keyboard);
        add_letters(keyboard, row, rows[index]);
    }
    lv_obj_t *row = make_row(keyboard);
    (void)add_key(keyboard, row, "mode:en", "ABC", 2, false);
    (void)add_key(keyboard, row, symbols ? "mode:numeric" : "mode:symbols",
                  symbols ? "123" : "#+=", 2, false);
    (void)add_key(keyboard, row, "space", "空格", 4, false);
    (void)add_key(keyboard, row, "backspace", LV_SYMBOL_BACKSPACE, 2, false);
    (void)add_key(keyboard, row, "enter", LV_SYMBOL_NEW_LINE, 2, true);
}

static void rebuild_keys(keyboard_t *keyboard)
{
    keyboard->key_count = 0U;
    lv_obj_clean(keyboard->keys);
    if(strcmp(keyboard->mode, "numeric") == 0)
        build_numeric_layout(keyboard, false);
    else if(strcmp(keyboard->mode, "symbols") == 0)
        build_numeric_layout(keyboard, true);
    else
        build_letter_layout(keyboard);
    keyboard->layout_key_count = keyboard->key_count;
    lv_label_set_text(keyboard->mode_label,
                      strcmp(keyboard->mode, "zh") == 0 ? "中文"
                      : strcmp(keyboard->mode, "numeric") == 0 ? "数字"
                      : strcmp(keyboard->mode, "symbols") == 0 ? "符号"
                                                                : "EN");
}

static size_t parse_string_array(const char *raw, size_t length,
                                 char values[][64], size_t capacity)
{
    size_t count = 0U;
    size_t index = 0U;
    while(index < length && count < capacity) {
        size_t used = 0U;
        bool escaped = false;
        while(index < length && raw[index] != '"') index++;
        if(index >= length) break;
        index++;
        while(index < length) {
            char value = raw[index++];
            if(escaped) {
                escaped = false;
                if(value == 'n') value = '\n';
                if(used + 1U < 64U) values[count][used++] = value;
            }
            else if(value == '\\')
                escaped = true;
            else if(value == '"')
                break;
            else if(used + 1U < 64U)
                values[count][used++] = value;
        }
        values[count][used] = '\0';
        count++;
    }
    return count;
}

static void candidate_event_cb(lv_event_t *event)
{
    key_view_t *view = lv_event_get_user_data(event);
    key_event_cb(event);
    (void)view;
}

static void update_candidates(keyboard_t *keyboard, const char *json)
{
    const char *raw = NULL;
    size_t length = 0U;
    char composition[64] = "";
    char values[MAX_CANDIDATES][64];
    size_t count = 0U;
    size_t index;
    (void)json_string(json, "composition", composition, sizeof(composition));
    lv_label_set_text(keyboard->composition,
                      composition[0] == '\0' ? "拼音" : composition);
    if(msys_mipc_json_get_raw(json, "candidates", &raw, &length) ==
       MSYS_MIPC_OK)
        count = parse_string_array(raw, length, values, MAX_CANDIDATES);
    lv_obj_clean(keyboard->candidates);
    keyboard->key_count = keyboard->layout_key_count;
    for(index = 0U; index < count && keyboard->key_count < MAX_KEYS; index++) {
        key_view_t *view = &keyboard->key_views[keyboard->key_count++];
        lv_obj_t *button;
        lv_obj_t *label;
        memset(view, 0, sizeof(*view));
        view->owner = keyboard;
        (void)snprintf(view->token, sizeof(view->token), "candidate:%zu", index);
        button = lv_button_create(keyboard->candidates);
        view->button = button;
        lv_obj_add_style(button, msys_ui_theme_button(keyboard->theme),
                         LV_PART_MAIN);
        lv_obj_set_size(button, LV_SIZE_CONTENT, 30);
        lv_obj_set_style_bg_color(button, lv_color_hex(0xe9eef8),
                                  LV_PART_MAIN);
        lv_obj_set_style_text_color(button, lv_color_hex(0x182033),
                                    LV_PART_MAIN);
        label = lv_label_create(button);
        lv_label_set_text(label, values[index]);
        font(keyboard, label, 16);
        lv_obj_center(label);
        lv_obj_add_event_cb(button, candidate_event_cb, LV_EVENT_ALL, view);
    }
}

static void translate_y_cb(void *object, int32_t value)
{
    lv_obj_set_style_translate_y((lv_obj_t *)object, value, LV_PART_MAIN);
}

static void hide_done_cb(lv_timer_t *timer)
{
    keyboard_t *keyboard = lv_timer_get_user_data(timer);
    if(keyboard != NULL && !keyboard->visible)
        msys_ui_surface_hide(keyboard->surface);
    lv_timer_delete(timer);
}

static void set_visible(keyboard_t *keyboard, bool visible)
{
    lv_anim_t animation;
    uint16_t duration = msys_ui_motion_duration(keyboard->policy,
                                                MSYS_UI_MOTION_PAGE);
    keyboard->visible = visible;
    if(visible) msys_ui_surface_show(keyboard->surface);
    lv_anim_delete(keyboard->screen, translate_y_cb);
    lv_anim_init(&animation);
    lv_anim_set_var(&animation, keyboard->screen);
    lv_anim_set_exec_cb(&animation, translate_y_cb);
    lv_anim_set_values(&animation, visible ? 12 : 0, visible ? 0 : 12);
    lv_anim_set_duration(&animation, duration);
    lv_anim_start(&animation);
    if(!visible) {
        if(keyboard->policy->reduced_motion)
            msys_ui_surface_hide(keyboard->surface);
        else
            (void)lv_timer_create(hide_done_cb, duration + 15U, keyboard);
    }
}

static void handle_command(keyboard_t *keyboard, const char *json)
{
    char type[24];
    char mode[16];
    bool changed = false;
    if(!json_string(json, "type", type, sizeof(type))) return;
    if(strcmp(type, "state") == 0) {
        if(json_string(json, "mode", mode, sizeof(mode)) &&
           strcmp(mode, keyboard->mode) != 0) {
            (void)snprintf(keyboard->mode, sizeof(keyboard->mode), "%s", mode);
            changed = true;
        }
        bool shift = json_bool(json, "shift");
        if(shift != keyboard->shift) {
            keyboard->shift = shift;
            changed = true;
        }
        if(changed) rebuild_keys(keyboard);
        update_candidates(keyboard, json);
    }
    else if(strcmp(type, "show") == 0)
        set_visible(keyboard, true);
    else if(strcmp(type, "hide") == 0)
        set_visible(keyboard, false);
    else if(strcmp(type, "stop") == 0)
        msys_ui_runtime_stop(keyboard->runtime);
}

static void pump_commands(keyboard_t *keyboard)
{
    char chunk[2048];
    ssize_t received;
    do {
        received = read(STDIN_FILENO, chunk, sizeof(chunk));
        if(received > 0) {
            size_t amount = (size_t)received;
            if(amount > sizeof(keyboard->input) - keyboard->input_used)
                keyboard->input_used = 0U;
            if(amount <= sizeof(keyboard->input) - keyboard->input_used) {
                memcpy(keyboard->input + keyboard->input_used, chunk, amount);
                keyboard->input_used += amount;
            }
        }
    } while(received > 0);
    while(true) {
        char *newline = memchr(keyboard->input, '\n', keyboard->input_used);
        size_t length;
        if(newline == NULL) break;
        length = (size_t)(newline - keyboard->input);
        if(length > 0U && length < INPUT_BUFFER) {
            keyboard->input[length] = '\0';
            handle_command(keyboard, keyboard->input);
        }
        length++;
        memmove(keyboard->input, keyboard->input + length,
                keyboard->input_used - length);
        keyboard->input_used -= length;
    }
}

static void hide_key_cb(lv_event_t *event)
{
    key_event_cb(event);
}

static void build_ui_legacy(keyboard_t *keyboard)
{
    lv_obj_t *header;
    lv_obj_t *title;
    lv_obj_t *hide;
    lv_obj_t *hide_label;
    lv_obj_t *composition_row;
    key_view_t *hide_view;
    keyboard->screen = msys_ui_surface_screen(keyboard->surface);
    lv_obj_set_style_bg_color(keyboard->screen, lv_color_hex(0xf5f7fb),
                              LV_PART_MAIN);
    lv_obj_set_style_bg_opa(keyboard->screen, LV_OPA_COVER, LV_PART_MAIN);
    lv_obj_set_style_pad_all(keyboard->screen, 3, LV_PART_MAIN);
    lv_obj_set_style_pad_gap(keyboard->screen, 2, LV_PART_MAIN);
    lv_obj_set_flex_flow(keyboard->screen, LV_FLEX_FLOW_COLUMN);

    header = lv_obj_create(keyboard->screen);
    lv_obj_remove_style_all(header);
    lv_obj_set_size(header, LV_PCT(100), 30);
    lv_obj_set_style_pad_hor(header, 5, LV_PART_MAIN);
    lv_obj_set_style_pad_gap(header, 6, LV_PART_MAIN);
    lv_obj_set_flex_flow(header, LV_FLEX_FLOW_ROW);
    title = lv_label_create(header);
    lv_label_set_text(title, "触摸键盘");
    font(keyboard, title, 16);
    lv_obj_set_flex_grow(title, 1);
    keyboard->mode_label = lv_label_create(header);
    font(keyboard, keyboard->mode_label, 14);
    hide_view = &keyboard->hide_view;
    memset(hide_view, 0, sizeof(*hide_view));
    hide_view->owner = keyboard;
    (void)snprintf(hide_view->token, sizeof(hide_view->token), "hide");
    hide = lv_button_create(header);
    hide_view->button = hide;
    lv_obj_set_size(hide, 42, 28);
    lv_obj_add_style(hide, msys_ui_theme_button(keyboard->theme), LV_PART_MAIN);
    hide_label = lv_label_create(hide);
    lv_label_set_text(hide_label, LV_SYMBOL_DOWN);
    lv_obj_center(hide_label);
    lv_obj_add_event_cb(hide, hide_key_cb, LV_EVENT_ALL, hide_view);

    composition_row = lv_obj_create(keyboard->screen);
    lv_obj_remove_style_all(composition_row);
    lv_obj_set_size(composition_row, LV_PCT(100), 34);
    lv_obj_set_style_pad_gap(composition_row, 3, LV_PART_MAIN);
    lv_obj_set_flex_flow(composition_row, LV_FLEX_FLOW_ROW);
    keyboard->composition = lv_label_create(composition_row);
    lv_obj_set_width(keyboard->composition, 64);
    lv_label_set_long_mode(keyboard->composition, LV_LABEL_LONG_DOT);
    font(keyboard, keyboard->composition, 14);
    lv_obj_set_style_text_color(keyboard->composition, lv_color_hex(0x315bb5),
                                LV_PART_MAIN);
    keyboard->candidates = lv_obj_create(composition_row);
    lv_obj_remove_style_all(keyboard->candidates);
    lv_obj_set_height(keyboard->candidates, 34);
    lv_obj_set_flex_grow(keyboard->candidates, 1);
    lv_obj_set_style_pad_gap(keyboard->candidates, 3, LV_PART_MAIN);
    lv_obj_set_flex_flow(keyboard->candidates, LV_FLEX_FLOW_ROW);
    lv_obj_set_scroll_dir(keyboard->candidates, LV_DIR_HOR);
    lv_obj_set_scrollbar_mode(keyboard->candidates, LV_SCROLLBAR_MODE_ACTIVE);

    keyboard->keys = lv_obj_create(keyboard->screen);
    lv_obj_remove_style_all(keyboard->keys);
    lv_obj_set_width(keyboard->keys, LV_PCT(100));
    lv_obj_set_flex_grow(keyboard->keys, 1);
    lv_obj_set_style_pad_gap(keyboard->keys, 2, LV_PART_MAIN);
    lv_obj_set_flex_flow(keyboard->keys, LV_FLEX_FLOW_COLUMN);
    (void)snprintf(keyboard->mode, sizeof(keyboard->mode), "en");
    rebuild_keys(keyboard);
    lv_label_set_text(keyboard->composition, "拼音");
}

static int document_bind_cb(lv_xml_component_scope_t *scope, void *user_data)
{
    keyboard_t *keyboard = user_data;
    if(scope == NULL || keyboard == NULL || keyboard->theme == NULL) return -1;
    if(lv_xml_register_font(scope, "msys_14",
                            msys_ui_theme_font(keyboard->theme, 14)) != LV_RESULT_OK ||
       lv_xml_register_font(scope, "msys_16",
                            msys_ui_theme_font(keyboard->theme, 16)) != LV_RESULT_OK)
        return -1;
    return 0;
}

static bool build_ui_document(keyboard_t *keyboard, const char *path)
{
    msys_ui_document_config_t config = {
        .bind = document_bind_cb,
        .user_data = keyboard,
    };
    lv_obj_t *hide;
    lv_obj_t *surface_screen = msys_ui_surface_screen(keyboard->surface);
    keyboard->document = msys_ui_document_create(surface_screen, &config);
    if(keyboard->document == NULL ||
       msys_ui_document_load_file(keyboard->document, path) !=
           MSYS_UI_DOCUMENT_OK)
        return false;
    keyboard->screen = msys_ui_document_root(keyboard->document);
    keyboard->mode_label = msys_ui_document_find(keyboard->document, "mode");
    keyboard->composition = msys_ui_document_find(keyboard->document,
                                                   "composition");
    keyboard->candidates = msys_ui_document_find(keyboard->document,
                                                  "candidates");
    keyboard->keys = msys_ui_document_find(keyboard->document, "keys");
    hide = msys_ui_document_find(keyboard->document, "hide");
    if(keyboard->mode_label == NULL || keyboard->composition == NULL ||
       keyboard->candidates == NULL || keyboard->keys == NULL || hide == NULL)
        return false;
    lv_obj_set_scroll_dir(keyboard->candidates, LV_DIR_HOR);
    lv_obj_set_scrollbar_mode(keyboard->candidates, LV_SCROLLBAR_MODE_ACTIVE);
    memset(&keyboard->hide_view, 0, sizeof(keyboard->hide_view));
    keyboard->hide_view.owner = keyboard;
    keyboard->hide_view.button = hide;
    (void)snprintf(keyboard->hide_view.token,
                   sizeof(keyboard->hide_view.token), "hide");
    lv_obj_add_event_cb(hide, hide_key_cb, LV_EVENT_ALL,
                        &keyboard->hide_view);
    (void)snprintf(keyboard->mode, sizeof(keyboard->mode), "en");
    rebuild_keys(keyboard);
    lv_label_set_text(keyboard->composition, "拼音");
    return true;
}

static void usage(FILE *stream, const char *argv0)
{
    fprintf(stream,
            "usage: %s [--display :24] [--output spi|hdmi] [--visible] "
            "[--reduced-motion] [--x N --y N --width N --height N] "
            "[--ui FILE] [--run-ms N]\n",
            argv0);
}

int main(int argc, char **argv)
{
    msys_ui_runtime_config_t runtime_config = {0};
    msys_ui_surface_config_t surface_config = {
        .x = 4,
        .y = 234,
        .width = 312,
        .height = 202,
        .draw_rows = 40,
        .title = "MSYS Touch Input LVGL",
        .app_id = "org.msys.input.touch",
        .component_id = "org.msys.input.touch:keyboard-lvgl",
        .role = "input-method",
        .wm_instance = "keyboard-lvgl",
        .override_redirect = true,
    };
    keyboard_t keyboard;
    bool initially_visible = false;
    const char *ui_path = NULL;
    int flags;
    int index;
    memset(&keyboard, 0, sizeof(keyboard));
    runtime_config.output = MSYS_UI_OUTPUT_SPI;
    for(index = 1; index < argc; index++) {
        if(strcmp(argv[index], "--describe") == 0) {
            puts("{\"frontend\":\"lvgl\",\"bridge\":\"python-business\","
                 "\"font\":\"provider\",\"dirty\":\"exact\"}");
            return 0;
        }
        if(strcmp(argv[index], "--display") == 0 && index + 1 < argc)
            runtime_config.display_name = argv[++index];
        else if(strcmp(argv[index], "--output") == 0 && index + 1 < argc)
            runtime_config.output = strcmp(argv[++index], "hdmi") == 0
                                        ? MSYS_UI_OUTPUT_HDMI
                                        : MSYS_UI_OUTPUT_SPI;
        else if(strcmp(argv[index], "--visible") == 0)
            initially_visible = true;
        else if(strcmp(argv[index], "--reduced-motion") == 0)
            runtime_config.reduced_motion = true;
        else if(strcmp(argv[index], "--x") == 0 && index + 1 < argc)
            surface_config.x = atoi(argv[++index]);
        else if(strcmp(argv[index], "--y") == 0 && index + 1 < argc)
            surface_config.y = atoi(argv[++index]);
        else if(strcmp(argv[index], "--width") == 0 && index + 1 < argc)
            surface_config.width = (uint16_t)atoi(argv[++index]);
        else if(strcmp(argv[index], "--height") == 0 && index + 1 < argc)
            surface_config.height = (uint16_t)atoi(argv[++index]);
        else if(strcmp(argv[index], "--ui") == 0 && index + 1 < argc)
            ui_path = argv[++index];
        else if(strcmp(argv[index], "--run-ms") == 0 && index + 1 < argc)
            keyboard.stop_at_ms = monotonic_ms() + strtoull(argv[++index], NULL, 10);
        else {
            usage(stderr, argv[0]);
            return 2;
        }
    }
    if(surface_config.width < 240U || surface_config.height < 148U) return 2;
    keyboard.runtime = msys_ui_runtime_create(&runtime_config);
    if(keyboard.runtime == NULL) return 1;
    (void)msys_ui_dynamic_fonts_init(NULL);
    keyboard.policy = msys_ui_runtime_policy(keyboard.runtime);
    keyboard.surface = msys_ui_surface_create(keyboard.runtime, &surface_config);
    if(keyboard.surface == NULL) {
        msys_ui_dynamic_fonts_shutdown();
        msys_ui_runtime_destroy(keyboard.runtime);
        return 1;
    }
    keyboard.theme = msys_ui_theme_create(
        msys_ui_surface_display(keyboard.surface), keyboard.policy);
    if(keyboard.theme == NULL) {
        msys_ui_dynamic_fonts_shutdown();
        msys_ui_runtime_destroy(keyboard.runtime);
        return 1;
    }
    msys_ui_theme_set_font_provider(keyboard.theme,
                                    msys_ui_font_provider, NULL,
                                    "zh-CN");
    if(ui_path != NULL) {
        if(!build_ui_document(&keyboard, ui_path)) {
            fprintf(stderr, "input-lvgl: cannot load dynamic UI %s\n", ui_path);
            msys_ui_document_destroy(keyboard.document);
            msys_ui_theme_destroy(keyboard.theme);
            msys_ui_dynamic_fonts_shutdown();
            msys_ui_runtime_destroy(keyboard.runtime);
            return 1;
        }
    }
    else
        build_ui_legacy(&keyboard);
    flags = fcntl(STDIN_FILENO, F_GETFL, 0);
    if(flags >= 0) (void)fcntl(STDIN_FILENO, F_SETFL, flags | O_NONBLOCK);
    if(initially_visible) {
        keyboard.standalone = true;
        set_visible(&keyboard, true);
    }
    else
        msys_ui_surface_hide(keyboard.surface);
    active_keyboard = &keyboard;
    (void)signal(SIGINT, signal_cb);
    (void)signal(SIGTERM, signal_cb);
    while((keyboard.stop_at_ms == 0U ||
           monotonic_ms() < keyboard.stop_at_ms) &&
          !msys_ui_surface_closed(keyboard.surface) &&
          msys_ui_runtime_step(keyboard.runtime, 20U) > 0) {
        pump_commands(&keyboard);
    }
    msys_ui_document_destroy(keyboard.document);
    msys_ui_theme_destroy(keyboard.theme);
    msys_ui_dynamic_fonts_shutdown();
    msys_ui_runtime_destroy(keyboard.runtime);
    active_keyboard = NULL;
    return 0;
}
