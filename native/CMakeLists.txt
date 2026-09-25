cmake_minimum_required(VERSION 3.16)
project(pymcl_bridge C)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

add_compile_options(-Wall -Wno-unused-parameter -Wno-unused-function)
add_compile_definitions(UNICODE _UNICODE WIN32_LEAN_AND_MEAN)

include_directories(${CMAKE_SOURCE_DIR}/include ${CMAKE_SOURCE_DIR}/vendor)

file(GLOB SRC src/*.c)
add_executable(pymcl-bridge
  ${SRC}
  vendor/cJSON.c
)

# Static link: src/ has zero libcurl calls (HTTP/TLS goes through WinHTTP /
# schannel), and -static folds libwinpthread + zlib into the exe so the build
# ships no side-by-side DLLs at all.
target_link_options(pymcl-bridge PRIVATE -static)

target_link_libraries(pymcl-bridge PRIVATE
  z
  bcrypt
  crypt32
  ws2_32
  winhttp
  pthread
  ole32
  shell32
)

set_target_properties(pymcl-bridge PROPERTIES
  RUNTIME_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/build
  RUNTIME_OUTPUT_DIRECTORY_RELEASE ${CMAKE_SOURCE_DIR}/build
  RUNTIME_OUTPUT_DIRECTORY_DEBUG ${CMAKE_SOURCE_DIR}/build
)

# No curl-ca-bundle.crt and no side-by-side DLL copying: WinHTTP uses the
# Windows certificate store, and -static folds the MinGW runtime in.
# Verified: objdump -p shows only KERNEL32 / SHELL32 / WINHTTP / WS2_32 /
# bcrypt / msvcrt imports.
