cmake_minimum_required(VERSION 3.20)
project(block01_exact_kt LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

add_compile_options(-Wall -Wextra -Werror -ffp-contract=off)

add_library(block01_kt STATIC src/kt_engine.cpp)
target_include_directories(block01_kt PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_compile_definitions(block01_kt PRIVATE _FILE_OFFSET_BITS=64)

add_executable(kt_stream src/kt_stream.cpp)
target_link_libraries(kt_stream PRIVATE block01_kt)

add_executable(generate_corpus src/generate_corpus.cpp)
target_include_directories(generate_corpus PRIVATE ${CMAKE_CURRENT_SOURCE_DIR} ${CMAKE_CURRENT_SOURCE_DIR}/include)
target_link_libraries(generate_corpus PRIVATE block01_kt)

add_executable(core_tests tests/core_tests.cpp)
target_link_libraries(core_tests PRIVATE block01_kt)

include(CTest)
if(BUILD_TESTING)
  add_test(NAME core_tests COMMAND core_tests)
endif()

install(TARGETS kt_stream generate_corpus RUNTIME DESTINATION bin)
install(FILES block01.py DESTINATION lib/block01)
