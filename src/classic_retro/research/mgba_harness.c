/* Classic Retro mGBA harness: one game under libmgba, driven over a pipe.
 *
 * classic_retro.research.mgba builds this file against the user's libmgba on
 * first use and talks to it one command per line on stdin; every reply is one
 * line on stdout, and a binary payload follows its line exactly.
 *
 *   (on start)                 -> ready PLATFORM WIDTH HEIGHT VERSION
 *   run FRAMES KEYS            -> hit {json}* then ok
 *   screen                     -> ok WIDTH HEIGHT, then WIDTH*HEIGHT*3 bytes (RGB)
 *   save                       -> ok SIZE, then SIZE bytes
 *   load SIZE + SIZE bytes     -> ok
 *   read ADDRESS LENGTH        -> ok LENGTH, then LENGTH bytes
 *   write ADDRESS LENGTH + LENGTH bytes -> ok
 *   break ADDRESS COUNT MEMKIND MEMVALUE MEMLENGTH -> ok ID
 *       COUNT -1 = every hit; MEMKIND 0 none, 1 register MEMVALUE, 2 address MEMVALUE
 *   watch ADDRESS TYPE COUNT   -> ok ID (TYPE: mWatchpointType)
 *   clear                      -> ok
 *   reset                      -> ok
 *   quit
 *
 * A failed command replies "error MESSAGE". Numbers are decimal or 0x hex.
 */
/* The installed build's feature flags come first: they decide the layout of
 * libmgba's structures (mGBA 0.10 and later install them). */
#if defined(__has_include)
#if __has_include(<mgba/flags.h>)
#include <mgba/flags.h>
#endif
#endif
#include <mgba/core/core.h>
#include <mgba/core/interface.h>
#include <mgba/core/log.h>
#include <mgba/core/version.h>
#include <mgba/debugger/debugger.h>
#include <mgba/internal/arm/arm.h>
#include <mgba/internal/sm83/sm83.h>

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

#ifdef COLOR_16_BIT
#error "The harness reads 32-bit mGBA frames; this libmgba was built with COLOR_16_BIT"
#endif

/* The largest frame an mGBA core draws: a Super Game Boy border. */
#define MAX_WIDTH 256
#define MAX_HEIGHT 224
#define MAX_POINTS 256

static struct mCore* core;
static color_t video[MAX_WIDTH * MAX_HEIGHT];
static struct mDebugger debugger;
static int run_frame;

static struct {
	ssize_t id;
	int active;
	int remaining; /* -1: every hit */
	int mem_kind;
	uint32_t mem_value;
	uint32_t mem_length;
} points[MAX_POINTS];
static int point_count;

static void log_nothing(struct mLogger* logger, int category, enum mLogLevel level, const char* format,
                        va_list args) {
	(void) logger;
	(void) category;
	(void) level;
	(void) format;
	(void) args;
}

static struct mLogger quiet_logger = {.log = log_nothing};

static void reply(const char* format, ...) {
	va_list args;
	va_start(args, format);
	vprintf(format, args);
	va_end(args);
	putchar('\n');
	fflush(stdout);
}

static int point_for(ssize_t id) {
	for (int i = 0; i < point_count; ++i) {
		if (points[i].active && points[i].id == id) {
			return i;
		}
	}
	return -1;
}

static void print_registers(void) {
	printf("\"registers\":{");
	if (core->platform(core) == mPLATFORM_GBA) {
		struct ARMCore* cpu = core->cpu;
		for (int r = 0; r < 16; ++r) {
			printf("\"r%d\":%u,", r, (uint32_t) cpu->gprs[r]);
		}
		printf("\"cpsr\":%u", (uint32_t) cpu->cpsr.packed);
	} else {
		struct SM83Core* cpu = core->cpu;
		printf("\"af\":%u,\"bc\":%u,\"de\":%u,\"hl\":%u,\"sp\":%u,\"pc\":%u", cpu->af, cpu->bc, cpu->de,
		       cpu->hl, cpu->sp, cpu->pc);
	}
	printf("}");
}

static void print_memory(int point) {
	uint32_t address = points[point].mem_value;
	if (points[point].mem_kind == 1) {
		struct ARMCore* cpu = core->cpu;
		address = (uint32_t) cpu->gprs[points[point].mem_value];
	}
	printf(",\"memory_address\":%u,\"memory\":\"", address);
	for (uint32_t i = 0; i < points[point].mem_length; ++i) {
		printf("%02x", core->busRead8(core, address + i) & 0xFF);
	}
	printf("\"");
}

static void spend(int point) {
	if (points[point].remaining > 0 && --points[point].remaining == 0) {
		debugger.platform->clearBreakpoint(debugger.platform, points[point].id);
		points[point].active = 0;
	}
}

static void entered(struct mDebugger* d, enum mDebuggerEntryReason reason, struct mDebuggerEntryInfo* info) {
	d->state = DEBUGGER_RUNNING;
	if (!info || (reason != DEBUGGER_ENTER_BREAKPOINT && reason != DEBUGGER_ENTER_WATCHPOINT)) {
		return;
	}
	int point = point_for(info->pointId);
	if (point < 0) {
		return;
	}
	printf("hit {\"id\":%ld,\"frame\":%d,\"address\":%u,", (long) points[point].id, run_frame, info->address);
	if (reason == DEBUGGER_ENTER_WATCHPOINT) {
		int write = info->type.wp.accessType & WATCHPOINT_WRITE;
		printf("\"kind\":\"watch\",\"access\":\"%s\",\"old\":%u,\"new\":%u,", write ? "write" : "read",
		       info->type.wp.oldValue, info->type.wp.newValue);
	} else {
		printf("\"kind\":\"break\",");
	}
	print_registers();
	if (points[point].mem_kind) {
		print_memory(point);
	}
	printf("}\n");
	spend(point);
}

static void paused(struct mDebugger* d) {
	d->state = DEBUGGER_RUNNING;
}

static int any_points(void) {
	for (int i = 0; i < point_count; ++i) {
		if (points[i].active) {
			return 1;
		}
	}
	return 0;
}

static int read_exact(void* buffer, size_t size) {
	return fread(buffer, 1, size, stdin) == size;
}

static void write_payload(const void* buffer, size_t size) {
	fwrite(buffer, 1, size, stdout);
	fflush(stdout);
}

static void command_run(unsigned long frames, unsigned long keys) {
	core->setKeys(core, (uint32_t) keys);
	for (run_frame = 0; run_frame < (int) frames; ++run_frame) {
		if (any_points()) {
			mDebuggerRunFrame(&debugger);
		} else {
			core->runFrame(core);
		}
	}
	reply("ok");
}

static void command_screen(void) {
	unsigned width, height;
	core->desiredVideoDimensions(core, &width, &height);
	if (width > MAX_WIDTH || height > MAX_HEIGHT) {
		reply("error frame of %ux%u exceeds the harness buffer", width, height);
		return;
	}
	unsigned char* rgb = malloc((size_t) width * height * 3);
	if (!rgb) {
		reply("error out of memory");
		return;
	}
	for (unsigned y = 0; y < height; ++y) {
		for (unsigned x = 0; x < width; ++x) {
			uint32_t colour = video[y * MAX_WIDTH + x];
			unsigned char* pixel = &rgb[(y * width + x) * 3];
			pixel[0] = colour & 0xFF;
			pixel[1] = (colour >> 8) & 0xFF;
			pixel[2] = (colour >> 16) & 0xFF;
		}
	}
	reply("ok %u %u", width, height);
	write_payload(rgb, (size_t) width * height * 3);
	free(rgb);
}

static void command_save(void) {
	size_t size = core->stateSize(core);
	void* state = calloc(1, size);
	if (!state || !core->saveState(core, state)) {
		free(state);
		reply("error the core could not save its state");
		return;
	}
	reply("ok %zu", size);
	write_payload(state, size);
	free(state);
}

static void command_load(unsigned long size) {
	void* state = malloc(size ? size : 1);
	if (!state || !read_exact(state, size)) {
		free(state);
		reply("error state data ended early");
		return;
	}
	if (size != core->stateSize(core)) {
		reply("error the state holds %lu bytes; this core's states hold %zu", size, core->stateSize(core));
	} else if (!core->loadState(core, state)) {
		reply("error the core rejected the state");
	} else {
		reply("ok");
	}
	free(state);
}

static void command_read(unsigned long address, unsigned long length) {
	unsigned char* data = malloc(length ? length : 1);
	if (!data) {
		reply("error out of memory");
		return;
	}
	for (unsigned long i = 0; i < length; ++i) {
		data[i] = core->busRead8(core, (uint32_t) (address + i));
	}
	reply("ok %lu", length);
	write_payload(data, length);
	free(data);
}

static void command_write(unsigned long address, unsigned long length) {
	unsigned char* data = malloc(length ? length : 1);
	if (!data || !read_exact(data, length)) {
		free(data);
		reply("error write data ended early");
		return;
	}
	for (unsigned long i = 0; i < length; ++i) {
		core->busWrite8(core, (uint32_t) (address + i), data[i]);
	}
	free(data);
	reply("ok");
}

static int new_point(ssize_t id, long count) {
	if (id < 0) {
		return -1;
	}
	int point = point_count++;
	points[point].id = id;
	points[point].active = 1;
	points[point].remaining = count < 0 ? -1 : (int) count;
	points[point].mem_kind = 0;
	return point;
}

static void command_break(unsigned long address, long count, int mem_kind, unsigned long mem_value,
                          unsigned long mem_length) {
	if (point_count == MAX_POINTS) {
		reply("error at most %d breakpoints and watchpoints", MAX_POINTS);
		return;
	}
	struct mBreakpoint breakpoint = {0};
	breakpoint.address = (uint32_t) address;
	breakpoint.segment = -1;
	breakpoint.type = BREAKPOINT_HARDWARE;
	int point = new_point(debugger.platform->setBreakpoint(debugger.platform, &breakpoint), count);
	if (point < 0) {
		reply("error the debugger refused a breakpoint at 0x%08lx", address);
		return;
	}
	points[point].mem_kind = mem_kind;
	points[point].mem_value = (uint32_t) mem_value;
	points[point].mem_length = (uint32_t) mem_length;
	reply("ok %ld", (long) points[point].id);
}

static void command_watch(unsigned long address, int type, long count) {
	if (point_count == MAX_POINTS) {
		reply("error at most %d breakpoints and watchpoints", MAX_POINTS);
		return;
	}
	struct mWatchpoint watchpoint = {0};
	watchpoint.address = (uint32_t) address;
	watchpoint.segment = -1;
	watchpoint.type = (enum mWatchpointType) type;
	int point = new_point(debugger.platform->setWatchpoint(debugger.platform, &watchpoint), count);
	if (point < 0) {
		reply("error the debugger refused a watchpoint at 0x%08lx", address);
		return;
	}
	reply("ok %ld", (long) points[point].id);
}

static void command_clear(void) {
	for (int i = 0; i < point_count; ++i) {
		if (points[i].active) {
			debugger.platform->clearBreakpoint(debugger.platform, points[i].id);
		}
	}
	point_count = 0;
	reply("ok");
}

int main(int argc, char** argv) {
	if (argc != 2) {
		fprintf(stderr, "usage: %s IMAGE\n", argv[0]);
		return 2;
	}
#ifdef _WIN32
	_setmode(_fileno(stdin), _O_BINARY);
	_setmode(_fileno(stdout), _O_BINARY);
#endif
	mLogSetDefaultLogger(&quiet_logger);
	core = mCoreFind(argv[1]);
	if (!core || !core->init(core)) {
		printf("error mGBA does not recognise %s as a game image\n", argv[1]);
		return 1;
	}
	mCoreInitConfig(core, NULL);
	core->setVideoBuffer(core, video, MAX_WIDTH);
	if (!mCoreLoadFile(core, argv[1])) {
		printf("error mGBA could not load %s\n", argv[1]);
		return 1;
	}
	core->reset(core);

	memset(&debugger, 0, sizeof(debugger));
	debugger.type = DEBUGGER_CUSTOM;
	debugger.entered = entered;
	debugger.paused = paused;
	mDebuggerAttach(&debugger, core);
	debugger.state = DEBUGGER_RUNNING;

	unsigned width, height;
	core->desiredVideoDimensions(core, &width, &height);
	reply("ready %s %u %u %s", core->platform(core) == mPLATFORM_GBA ? "gba" : "gb", width, height,
	      projectVersion);

	char line[512];
	while (fgets(line, sizeof(line), stdin)) {
		char* name = strtok(line, " \t\r\n");
		long long value[5] = {0};
		int count = 0;
		for (char* token = strtok(NULL, " \t\r\n"); token && count < 5; token = strtok(NULL, " \t\r\n")) {
			value[count++] = strtoll(token, NULL, 0);
		}
		if (!name) {
			continue;
		}
		if (!strcmp(name, "run") && count == 2) {
			command_run((unsigned long) value[0], (unsigned long) value[1]);
		} else if (!strcmp(name, "screen")) {
			command_screen();
		} else if (!strcmp(name, "save")) {
			command_save();
		} else if (!strcmp(name, "load") && count == 1) {
			command_load((unsigned long) value[0]);
		} else if (!strcmp(name, "read") && count == 2) {
			command_read((unsigned long) value[0], (unsigned long) value[1]);
		} else if (!strcmp(name, "write") && count == 2) {
			command_write((unsigned long) value[0], (unsigned long) value[1]);
		} else if (!strcmp(name, "break") && count == 5) {
			command_break((unsigned long) value[0], (long) value[1], (int) value[2], (unsigned long) value[3],
			              (unsigned long) value[4]);
		} else if (!strcmp(name, "watch") && count == 3) {
			command_watch((unsigned long) value[0], (int) value[1], (long) value[2]);
		} else if (!strcmp(name, "clear")) {
			command_clear();
		} else if (!strcmp(name, "reset")) {
			core->reset(core);
			reply("ok");
		} else if (!strcmp(name, "quit")) {
			break;
		} else {
			reply("error unknown command: %s", name);
		}
	}
	core->deinit(core);
	return 0;
}
