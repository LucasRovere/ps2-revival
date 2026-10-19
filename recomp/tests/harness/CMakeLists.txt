cmake_minimum_required(VERSION 3.20)
project(recomp-harness CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(HARNESS_CASES "" CACHE PATH "Folder with the case sources written by harness.py")

add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../../ps2-web-recomp upstream)

if(HARNESS_CASES)
    file(GLOB CASE_SOURCES CONFIGURE_DEPENDS "${HARNESS_CASES}/*.cpp")
    add_executable(harness main.cpp ${CASE_SOURCES})
    target_link_libraries(harness PRIVATE ps2runtime)
    target_compile_options(harness PRIVATE -Wno-unused-label -Wno-unused-variable)
endif()
