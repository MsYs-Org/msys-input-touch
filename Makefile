CC ?= cc
UI_ROOT ?= ../msys-ui-lvgl
SDK_ROOT ?= ../msys-sdk
BUILD_DIR ?= build

CPPFLAGS += -I$(UI_ROOT) -I$(UI_ROOT)/include -I$(UI_ROOT)/vendor/lvgl \
	-I$(SDK_ROOT)/include -DLV_CONF_INCLUDE_SIMPLE
CFLAGS ?= -Os -g0 -DNDEBUG
CFLAGS += -std=c11 -Wall -Wextra -Wpedantic -Werror \
	-ffunction-sections -fdata-sections
LDLIBS += -lX11 -lm -ldl

UI_LIBRARY := $(UI_ROOT)/build/libmsys-ui-lvgl.a
TARGET := $(BUILD_DIR)/msys-input-touch-lvgl
SOURCES := native/main.c $(SDK_ROOT)/src/mipc.c

.PHONY: all clean stage probe aarch64-build

all: $(TARGET)

$(UI_LIBRARY):
	$(MAKE) -C $(UI_ROOT) -j1 CC="$(CC)" AR="$(AR)" $(UI_LIBRARY:$(UI_ROOT)/%=%)

$(TARGET): $(SOURCES) $(UI_LIBRARY)
	@mkdir -p $(BUILD_DIR)
	$(CC) $(CPPFLAGS) $(CFLAGS) -Wl,--gc-sections $(SOURCES) \
		$(UI_LIBRARY) -o $@ $(LDLIBS)

stage: all
	@mkdir -p files/bin files/share/ui files/share/licenses/lvgl files/share/licenses/fonts
	install -m 0755 $(TARGET) files/bin/msys-input-touch-lvgl
	cp ui/keyboard.xml files/share/ui/
	cp $(UI_ROOT)/vendor/lvgl/LICENCE.txt files/share/licenses/lvgl/
	cp $(UI_ROOT)/fonts/NotoSansSC.LICENSE.txt files/share/licenses/fonts/

probe: all
	sh tests/xvfb_lvgl_smoke.sh

aarch64-build:
	sh scripts/build_aarch64_j1.sh

clean:
	rm -rf $(BUILD_DIR) files/bin files/share/licenses/lvgl \
		files/share/licenses/fonts files/share/ui
