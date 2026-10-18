#include <QGuiApplication>
#include <QQmlApplicationEngine>
#include <QQmlContext>
#include <QQuickStyle>
#include "Controller.h"

int main(int argc, char *argv[]) {
    QGuiApplication app(argc, argv);
    app.setApplicationName("视频下载器");
    app.setOrganizationName("LocalVideoDownloader");
    QQuickStyle::setStyle("Basic");
    Controller controller;
    QQmlApplicationEngine engine;
    engine.rootContext()->setContextProperty("downloadApp", &controller);
    QObject::connect(&engine, &QQmlApplicationEngine::objectCreationFailed,
                     &app, [] { QCoreApplication::exit(1); }, Qt::QueuedConnection);
    engine.loadFromModule("VideoDownloader", "Main");
    return app.exec();
}
