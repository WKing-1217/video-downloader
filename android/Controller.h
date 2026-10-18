#pragma once
#include <QObject>
#include <QJsonObject>

class Controller : public QObject {
    Q_OBJECT
    Q_PROPERTY(QString link READ link WRITE setLink NOTIFY changed)
    Q_PROPERTY(QString platform READ platform NOTIFY changed)
    Q_PROPERTY(QString title READ title NOTIFY changed)
    Q_PROPERTY(QString status READ status NOTIFY changed)
    Q_PROPERTY(QString details READ details NOTIFY changed)
    Q_PROPERTY(QString logs READ logs NOTIFY changed)
    Q_PROPERTY(bool busy READ busy NOTIFY changed)
    Q_PROPERTY(bool complete READ complete NOTIFY changed)
    Q_PROPERTY(double progress READ progress NOTIFY changed)
    Q_PROPERTY(QString version READ version CONSTANT)
    Q_PROPERTY(QString updateStatus READ updateStatus NOTIFY changed)
    Q_PROPERTY(bool updateAvailable READ updateAvailable NOTIFY changed)
    Q_PROPERTY(bool autoUpdate READ autoUpdate WRITE setAutoUpdate NOTIFY changed)
public:
    explicit Controller(QObject *parent = nullptr);
    QString link() const { return m_link; }
    QString platform() const { return m_platform; }
    QString title() const { return m_title; }
    QString status() const { return m_status; }
    QString details() const { return m_details; }
    QString logs() const { return m_logs; }
    bool busy() const { return m_busy; }
    bool complete() const { return !m_result.isEmpty(); }
    double progress() const { return m_progress; }
    QString version() const;
    QString updateStatus() const { return m_updateStatus; }
    bool updateAvailable() const { return m_updateAvailable; }
    bool autoUpdate() const;
    void setAutoUpdate(bool enabled);
    void setLink(const QString &text);
    void consume(const QString &line);
    Q_INVOKABLE void paste();
    Q_INVOKABLE void start();
    Q_INVOKABLE void cancel();
    Q_INVOKABLE void login();
    Q_INVOKABLE void openResult();
    Q_INVOKABLE void shareResult();
    Q_INVOKABLE void checkForUpdates(bool manual = true);
    Q_INVOKABLE void openUpdate();
signals:
    void changed();
private:
    QString m_link, m_platform, m_title = "等待一个好作品";
    QString m_status = "粘贴链接，或从其他软件分享到这里。";
    QString m_details = "保存到 下载 / 视频下载器", m_logs;
    bool m_busy = false;
    double m_progress = 0;
    QJsonObject m_result;
    QString m_updateStatus, m_updateUrl;
    bool m_updateAvailable = false;
};
