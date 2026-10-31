pipeline {
    agent { label 'release-builder' }
    options {
        skipDefaultCheckout(true)
        disableConcurrentBuilds()
        timeout(time: 35, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '25'))
    }
    parameters {
        choice(name: 'ACTION', choices: ['DEPLOY_GOOD', 'DEPLOY_UNHEALTHY', 'ROLLBACK', 'DEPLOY_POSTCHECK_FAIL'],
               description: 'Deploy a version, exercise a real failure, or restore the previous immutable image.')
    }
    environment { LAB_STATE_DIR = '/lab' }
    stages {
        stage('Checkout') {
            steps {
                checkout scm
                sh '''#!/bin/sh
set -eu
mkdir -p reports
find reports -maxdepth 1 -type f \\( -name '*.json' -o -name '*.xml' \\) -delete
'''
            }
        }
        stage('Fetch pinned upstream') {
            when { expression { params.ACTION != 'ROLLBACK' } }
            steps { sh '''#!/bin/sh
set -eu
python3 scripts/fetch_upstream.py
''' }
        }
        stage('PostgreSQL tests') {
            when { expression { params.ACTION != 'ROLLBACK' } }
            steps {
                withCredentials([string(credentialsId: 'lab-test-db-password', variable: 'LAB_TEST_DB_PASSWORD')]) {
                    sh '''#!/bin/sh
set -eu
python3 scripts/release.py test
'''
                }
            }
        }
        stage('Package immutable release') {
            when { expression { params.ACTION != 'ROLLBACK' } }
            steps { sh '''#!/bin/sh
set -eu
python3 scripts/release.py package
''' }
        }
        stage('Deploy or rollback') {
            steps {
                withCredentials([
                    string(credentialsId: 'lab-db-password', variable: 'LAB_DB_PASSWORD'),
                    string(credentialsId: 'lab-alpha-key', variable: 'LAB_ALPHA_API_KEY'),
                    string(credentialsId: 'lab-beta-key', variable: 'LAB_BETA_API_KEY')
                ]) {
                    sh '''#!/bin/sh
set -eu
python3 scripts/release.py deploy
'''
                }
            }
        }
        stage('Gateway post-check') {
            steps {
                withCredentials([
                    string(credentialsId: 'lab-db-password', variable: 'LAB_DB_PASSWORD'),
                    string(credentialsId: 'lab-alpha-key', variable: 'LAB_ALPHA_API_KEY'),
                    string(credentialsId: 'lab-beta-key', variable: 'LAB_BETA_API_KEY')
                ]) {
                    sh '''#!/bin/sh
set -eu
python3 scripts/release.py post
'''
                }
            }
        }
    }
    post {
        always {
            withCredentials([
                string(credentialsId: 'lab-db-password', variable: 'LAB_DB_PASSWORD'),
                string(credentialsId: 'lab-test-db-password', variable: 'LAB_TEST_DB_PASSWORD'),
                string(credentialsId: 'lab-alpha-key', variable: 'LAB_ALPHA_API_KEY'),
                string(credentialsId: 'lab-beta-key', variable: 'LAB_BETA_API_KEY')
            ]) {
                sh '''#!/bin/sh
set -eu
python3 scripts/release.py audit-reports
'''
                junit testResults: 'reports/test-results.xml', allowEmptyResults: true, keepLongStdio: false
                archiveArtifacts artifacts: 'reports/*.json,reports/*.xml', allowEmptyArchive: true, fingerprint: true
            }
        }
    }
}
