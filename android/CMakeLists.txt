cmake_minimum_required(VERSION 3.22)
project(VideoDownloader VERSION 1.0 LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/../bilibili/version.json" release_identity)
string(JSON app_version GET "${release_identity}" version)
string(JSON android_version_code GET "${release_identity}" android_version_code)
find_package(Qt6 6.8 REQUIRED COMPONENTS Quick QuickControls2)
qt_standard_project_setup(REQUIRES 6.8)
qt_add_executable(VideoDownloader main.cpp Controller.cpp Controller.h)
qt_add_qml_module(VideoDownloader URI VideoDownloader VERSION 1.0 QML_FILES Main.qml)
target_link_libraries(VideoDownloader PRIVATE Qt6::Quick Qt6::QuickControls2)
target_compile_definitions(VideoDownloader PRIVATE APP_VERSION="${app_version}")
set_target_properties(VideoDownloader PROPERTIES
    QT_ANDROID_PACKAGE_SOURCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/package"
    QT_ANDROID_PACKAGE_NAME "com.localvideodownloader.app"
    QT_ANDROID_APP_NAME "视频下载器"
    QT_ANDROID_VERSION_CODE "${android_version_code}"
    QT_ANDROID_VERSION_NAME "${app_version}"
    QT_ANDROID_MIN_SDK_VERSION 29
    QT_ANDROID_TARGET_SDK_VERSION 36
    QT_ANDROID_COMPILE_SDK_VERSION 36)
