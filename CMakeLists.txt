cmake_minimum_required(VERSION 3.23)
project(OniProfiler VERSION 1.0.0 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
option(ONIPROFILER_OFFLINE_TESTS_ONLY "Build dependency-free OniProfiler tests without fetching native dependencies" OFF)
include(CTest)
find_package(Threads REQUIRED)
find_package(Python3 REQUIRED COMPONENTS Interpreter)

add_executable(oni_domain_tests tests/domain_test.cpp src/oni/report_writer.cpp)
target_include_directories(oni_domain_tests PRIVATE src)
target_link_libraries(oni_domain_tests PRIVATE Threads::Threads)
if(WIN32)
    target_compile_definitions(oni_domain_tests PRIVATE NOMINMAX)
endif()
add_test(NAME oni_domain COMMAND oni_domain_tests)
add_test(NAME oni_python_tools COMMAND ${Python3_EXECUTABLE} -m unittest discover -s tests -p test_*.py)
set_tests_properties(oni_python_tools PROPERTIES WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR})
find_program(NODE_EXECUTABLE node)
if(NODE_EXECUTABLE)
    add_test(NAME oni_web_data COMMAND ${NODE_EXECUTABLE} --test ${CMAKE_CURRENT_SOURCE_DIR}/tests/web_data.test.cjs)
endif()
add_executable(oni_bridge_tests tests/bridge_test.cpp src/oni/command_bridge.cpp)
target_include_directories(oni_bridge_tests PRIVATE src)
target_link_libraries(oni_bridge_tests PRIVATE Threads::Threads)
add_test(NAME oni_bridge COMMAND oni_bridge_tests)
set_tests_properties(oni_python_tools PROPERTIES ENVIRONMENT "ONI_BRIDGE_TEST_EXE=$<TARGET_FILE:oni_bridge_tests>")
if(NODE_EXECUTABLE)
    add_test(NAME oni_runtime_sdk COMMAND ${NODE_EXECUTABLE} --test ${CMAKE_CURRENT_SOURCE_DIR}/tests/runtime_sdk.test.mjs)
endif()
if(ONIPROFILER_OFFLINE_TESTS_ONLY)
    return()
endif()

include(FetchContent)
# Native release source archives include these exact, already patched checkouts.
foreach(dependency spark_engine endstone endstone_papi_headers funchook)
    string(TOUPPER "${dependency}" dependency_upper)
    if(IS_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/upstream-src/${dependency}-src")
        set(FETCHCONTENT_SOURCE_DIR_${dependency_upper}
            "${CMAKE_CURRENT_SOURCE_DIR}/upstream-src/${dependency}-src" CACHE PATH "Bundled dependency checkout")
    endif()
endforeach()
# Spark remains an identifiable upstream dependency. The standalone Spark plugin
# is not packaged or installed. Only the native libraries and adapters are linked.
FetchContent_Declare(spark_engine
    GIT_REPOSITORY https://github.com/EndstoneMC/spark.git
    GIT_TAG 8958173ad40c1da9adf3254305526443c9853848
    GIT_SHALLOW FALSE
    GIT_CONFIG core.autocrlf=false core.eol=lf
    SOURCE_SUBDIR oniprofiler-do-not-auto-add)
FetchContent_MakeAvailable(spark_engine)
execute_process(COMMAND ${Python3_EXECUTABLE} ${CMAKE_CURRENT_SOURCE_DIR}/tools/patch_engine.py ${spark_engine_SOURCE_DIR}
    RESULT_VARIABLE patch_result)
if(NOT patch_result EQUAL 0)
    message(FATAL_ERROR "Pinned Spark integration did not verify; refusing a best-effort native build")
endif()
add_subdirectory(${spark_engine_SOURCE_DIR} ${spark_engine_BINARY_DIR})
set_target_properties(spark PROPERTIES EXCLUDE_FROM_ALL TRUE EXCLUDE_FROM_DEFAULT_BUILD TRUE)

endstone_add_plugin(oniprofiler
    src/plugin.cpp src/oni/control_center.cpp src/oni/options.cpp src/oni/report_writer.cpp src/oni/command_bridge.cpp
    ${spark_engine_SOURCE_DIR}/src/platform/endstone/adapters.cpp
    ${spark_engine_SOURCE_DIR}/src/platform/endstone/native_plugin_attribution.cpp)
target_include_directories(oniprofiler PRIVATE src ${spark_engine_SOURCE_DIR}/src)
target_link_libraries(oniprofiler PRIVATE spark_application spark_papi_integration)
set_target_properties(oniprofiler PROPERTIES PREFIX "" OUTPUT_NAME "endstone_oniprofiler")
if(WIN32)
    target_compile_definitions(oniprofiler PRIVATE NOMINMAX)
elseif(CMAKE_SYSTEM_NAME STREQUAL "Linux" AND CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(oniprofiler PRIVATE -fvisibility=hidden -fvisibility-inlines-hidden)
    target_link_options(oniprofiler PRIVATE "-Wl,--exclude-libs,ALL")
endif()
