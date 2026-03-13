package com.penguinoo.codexmobile;

public final class ChatHeaderModel {
    private ChatHeaderModel() {
    }

    public static String metadataLine(SessionSummary session, String proxySummary) {
        String primaryLine = "";
        if (session != null) {
            if (session.note != null && !session.note.isEmpty()) {
                primaryLine = session.note;
            } else if (session.cwd != null) {
                primaryLine = session.cwd;
            }
        }
        String model = session == null || session.model == null || session.model.isEmpty() ? "default" : session.model;
        String approval = session == null || session.approvalPolicy == null || session.approvalPolicy.isEmpty() ? "default" : session.approvalPolicy;
        String sandbox = session == null || session.sandboxMode == null || session.sandboxMode.isEmpty() ? "default" : session.sandboxMode;
        String proxy = proxySummary == null || proxySummary.isEmpty() ? "default" : proxySummary;
        String settingsLine = "Model " + model
                + " | Approval " + approval
                + " | Sandbox " + sandbox
                + " | Proxy " + proxy;
        if (primaryLine.isEmpty()) {
            return settingsLine;
        }
        return primaryLine + "\n" + settingsLine;
    }
}
