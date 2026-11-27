cmake_minimum_required(VERSION 3.16)
project(claudegg_wiiu_bridge C)

# Vanilla (https://github.com/vanilla-wiiu/vanilla, GPL-2.0) does the Wii U
# GamePad protocol. Only its library ("lib/") is built here; the Wi-Fi part
# runs in the separate program vanilla-pipe from Vanilla itself.
include(FetchContent)
set(VANILLA_COMMIT 01114a668ac85f4ef3d3c4433753d48c8792d903 CACHE STRING "Vanilla commit to build against")
FetchContent_Declare(vanilla
    GIT_REPOSITORY https://github.com/vanilla-wiiu/vanilla.git
    GIT_TAG ${VANILLA_COMMIT}
)
FetchContent_GetProperties(vanilla)
if (NOT vanilla_POPULATED)
    FetchContent_Populate(vanilla)
endif()
add_subdirectory(${vanilla_SOURCE_DIR}/lib ${CMAKE_BINARY_DIR}/libvanilla)

add_executable(claudegg-wiiu-bridge bridge.c)
target_include_directories(claudegg-wiiu-bridge PRIVATE ${vanilla_SOURCE_DIR}/lib)
target_link_libraries(claudegg-wiiu-bridge PRIVATE libvanilla pthread m)
target_compile_options(claudegg-wiiu-bridge PRIVATE -Wall -Wextra)
install(TARGETS claudegg-wiiu-bridge)
